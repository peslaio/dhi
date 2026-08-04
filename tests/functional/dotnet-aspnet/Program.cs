using System.Collections.Concurrent;
using System.IO.Compression;
using System.Net;
using System.Net.Http.Json;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;

var builder = WebApplication.CreateBuilder(new WebApplicationOptions
{
    Args = args,
    ContentRootPath = AppContext.BaseDirectory
});
var checks = await RuntimeChecks.RunAsync(builder.Configuration);
var state = new ReadinessState(checks);

builder.Services.AddHealthChecks();

var app = builder.Build();
app.Lifetime.ApplicationStopping.Register(() => state.Ready = false);

app.MapGet("/", async (HttpContext context) =>
{
    if (!state.Ready)
    {
        await state.WaitUntilReadyAsync(context.RequestAborted);
    }

    return state.Ready
        ? Results.Json(new { status = "dotnet-aspnet-app-ok", checks = state.Checks.ToArray() })
        : Results.Json(new { status = "starting", checks = state.Checks.ToArray() }, statusCode: StatusCodes.Status503ServiceUnavailable);
});

app.MapGet("/internal", () => Results.Json(new { status = "dotnet-aspnet-internal-ok" }));

app.MapPost("/model", (ProbeRequest request) =>
{
    if (string.IsNullOrWhiteSpace(request.Message) || request.Count is < 1 or > 5)
    {
        return Results.ValidationProblem(new Dictionary<string, string[]>
        {
            ["request"] = ["message must be non-empty and count must be between 1 and 5"]
        });
    }

    return Results.Ok(new ProbeResponse(request.Message.Trim(), request.Count, "aspnet-model-ok"));
});

app.MapGet("/stream", async context =>
{
    context.Response.ContentType = "text/plain; charset=utf-8";
    await context.Response.WriteAsync("chunk-1|", context.RequestAborted);
    await context.Response.Body.FlushAsync(context.RequestAborted);
    await Task.Yield();
    await context.Response.WriteAsync("chunk-2", context.RequestAborted);
});

app.MapHealthChecks("/health/live");

await app.StartAsync();
try
{
    RuntimeChecks.Require(app.Lifetime.ApplicationStarted.IsCancellationRequested, "Generic Host did not signal ApplicationStarted");
    state.Checks.Enqueue("generic-host-start");
    await EndpointChecks.RunAsync(state.Checks);
    state.MarkReady();
    Console.WriteLine($"ASP.NET startup checks passed: {string.Join(',', state.Checks)}");
    await app.WaitForShutdownAsync();
}
finally
{
    state.Ready = false;
    await app.StopAsync();
}

internal static class EndpointChecks
{
    internal static async Task RunAsync(ConcurrentQueue<string> checks)
    {
        using var handler = new SocketsHttpHandler { UseProxy = false };
        using var client = new HttpClient(handler)
        {
            BaseAddress = new Uri("http://127.0.0.1:8080"),
            Timeout = TimeSpan.FromSeconds(5)
        };

        var internalResponse = await client.GetAsync("/internal");
        RuntimeChecks.Require(internalResponse.StatusCode == HttpStatusCode.OK, "internal route returned a non-200 status");
        RuntimeChecks.Require((await internalResponse.Content.ReadAsStringAsync()).Contains("dotnet-aspnet-internal-ok", StringComparison.Ordinal), "internal route returned the wrong body");

        var missingResponse = await client.GetAsync("/missing");
        RuntimeChecks.Require(missingResponse.StatusCode == HttpStatusCode.NotFound, "routing negative probe did not return 404");

        var healthResponse = await client.GetAsync("/health/live");
        RuntimeChecks.Require(healthResponse.StatusCode == HttpStatusCode.OK, "health endpoint was not healthy");
        checks.Enqueue("routing-health");

        var validResponse = await client.PostAsJsonAsync("/model", new ProbeRequest("model-value", 3));
        RuntimeChecks.Require(validResponse.StatusCode == HttpStatusCode.OK, "valid model was rejected");
        RuntimeChecks.Require((await validResponse.Content.ReadAsStringAsync()).Contains("aspnet-model-ok", StringComparison.Ordinal), "valid model response was wrong");

        var invalidResponse = await client.PostAsJsonAsync("/model", new ProbeRequest("", 0));
        RuntimeChecks.Require(invalidResponse.StatusCode == HttpStatusCode.BadRequest, "invalid model was not rejected");
        checks.Enqueue("model-binding-validation");

        var streamResponse = await client.GetAsync("/stream", HttpCompletionOption.ResponseHeadersRead);
        RuntimeChecks.Require(streamResponse.StatusCode == HttpStatusCode.OK, "streaming endpoint returned a non-200 status");
        RuntimeChecks.Require(await streamResponse.Content.ReadAsStringAsync() == "chunk-1|chunk-2", "streaming response was incomplete");
        checks.Enqueue("streaming");
        checks.Enqueue("local-http");
    }
}

internal static class RuntimeChecks
{
    internal static async Task<ConcurrentQueue<string>> RunAsync(IConfiguration configuration)
    {
        var checks = new ConcurrentQueue<string>();
        var configPath = Environment.GetEnvironmentVariable("DHI_CONFIG_PATH") ?? Path.Combine(AppContext.BaseDirectory, "appsettings.json");
        using var configDocument = JsonDocument.Parse(await File.ReadAllTextAsync(configPath, Encoding.UTF8));
        var fileSection = configDocument.RootElement.GetProperty("Dhi");
        Require(fileSection.GetProperty("Mode").GetString() == "file", "file configuration was not loaded");
        Require(configuration["Dhi:Mode"] == "environment", "environment did not override file configuration");
        Require(configuration["Dhi:Label"] == "dotnet-aspnet", "unexpected configuration label");
        checks.Enqueue("config-precedence");

        var json = JsonSerializer.Serialize(new JsonProbe("Zażółć ☃", 3));
        Require(JsonSerializer.Deserialize<JsonProbe>(json) == new JsonProbe("Zażółć ☃", 3), "JSON round trip failed");
        checks.Enqueue("json");

        var temporaryDirectory = Directory.CreateTempSubdirectory("dhi-aspnet-");
        try
        {
            var temporaryFile = Path.Combine(temporaryDirectory.FullName, "probe.txt");
            await File.WriteAllTextAsync(temporaryFile, "aspnet-filesystem-ok", Encoding.UTF8);
            Require(await File.ReadAllTextAsync(temporaryFile, Encoding.UTF8) == "aspnet-filesystem-ok", "temporary file mismatch");
        }
        finally
        {
            temporaryDirectory.Delete(recursive: true);
        }
        checks.Enqueue("filesystem-tmp");

        Require((await Dns.GetHostAddressesAsync("localhost")).Length > 0, "localhost DNS lookup returned no addresses");
        checks.Enqueue("dns");

        var digest = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes("abc"))).ToLowerInvariant();
        Require(digest == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "SHA-256 mismatch");
        checks.Enqueue("crypto");

        await using var compressed = new MemoryStream();
        await using (var gzip = new GZipStream(compressed, CompressionMode.Compress, leaveOpen: true))
        {
            await gzip.WriteAsync(Encoding.UTF8.GetBytes("aspnet-compression-ok"));
        }
        compressed.Position = 0;
        using var decompressor = new GZipStream(compressed, CompressionMode.Decompress);
        using var decompressed = new StreamReader(decompressor, Encoding.UTF8);
        Require(await decompressed.ReadToEndAsync() == "aspnet-compression-ok", "gzip round trip failed");
        checks.Enqueue("compression");

        const string text = "Zażółć";
        Require(Encoding.UTF8.GetString(Encoding.UTF8.GetBytes(text)) == text, "UTF-8 round trip failed");
        Require(TimeZoneInfo.ConvertTime(DateTimeOffset.Parse("2020-01-01T00:00:00Z"), TimeZoneInfo.Utc).Offset == TimeSpan.Zero, "UTC timezone offset mismatch");
        checks.Enqueue("encoding-timezone");

        var workerResults = await Task.WhenAll(Enumerable.Range(1, 5).Select(number => Task.Run(() => number * number)));
        Require(workerResults.Sum() == 55, "thread-pool computation failed");
        checks.Enqueue("worker-threads");

        var method = typeof(RuntimeChecks).GetMethod(nameof(ReflectedChecksum), BindingFlags.NonPublic | BindingFlags.Static)
            ?? throw new InvalidOperationException("reflection target was not found");
        Require((int?)method.Invoke(null, new object[] { "aspnet" }) == 651, "reflection invocation failed");
        checks.Enqueue("reflection");

        Require(GetPid() == Environment.ProcessId, "native libc getpid mismatch");
        checks.Enqueue("native-libc");
        return checks;
    }

    internal static void Require(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }

    private static int ReflectedChecksum(string value) => value.Sum(character => character);

    [DllImport("libc", EntryPoint = "getpid")]
    private static extern int GetPid();

    private sealed record JsonProbe(string Text, int Count);
}

internal sealed class ReadinessState(ConcurrentQueue<string> checks)
{
    internal volatile bool Ready;
    internal ConcurrentQueue<string> Checks { get; } = checks;
    private TaskCompletionSource<bool> ReadySignal { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

    internal void MarkReady()
    {
        Ready = true;
        ReadySignal.TrySetResult(true);
    }

    internal async Task WaitUntilReadyAsync(CancellationToken cancellationToken)
    {
        try
        {
            await ReadySignal.Task.WaitAsync(TimeSpan.FromSeconds(5), cancellationToken);
        }
        catch (TimeoutException)
        {
        }
    }
}

internal sealed record ProbeRequest(string Message, int Count);
internal sealed record ProbeResponse(string Message, int Count, string Status);
