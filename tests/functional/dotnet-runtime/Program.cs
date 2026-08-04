using System.Collections.Concurrent;
using System.IO.Compression;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

internal static class Program
{
    private static async Task<int> Main()
    {
        var state = new RuntimeState();
        await RunStartupChecksAsync(state.Checks);

        using var shutdown = new CancellationTokenSource();
        using var sigterm = RegisterSignal(PosixSignal.SIGTERM, shutdown);
        using var sigint = RegisterSignal(PosixSignal.SIGINT, shutdown);
        var listener = new TcpListener(IPAddress.Any, 8080);
        var clients = new ConcurrentDictionary<int, Task>();

        listener.Start();
        var acceptLoop = AcceptLoopAsync(listener, state, clients, shutdown.Token);

        try
        {
            await ProbeLocalHttpAsync();
            state.Checks.Enqueue("local-http");
            state.MarkReady();
            Console.WriteLine($"dotnet runtime startup checks passed: {string.Join(',', state.Checks)}");
            await Task.Delay(Timeout.InfiniteTimeSpan, shutdown.Token);
        }
        catch (OperationCanceledException) when (shutdown.IsCancellationRequested)
        {
            // Expected graceful shutdown path for SIGTERM/SIGINT.
        }
        finally
        {
            state.Ready = false;
            shutdown.Cancel();
            listener.Stop();
            await ObserveCancellationAsync(acceptLoop);
            await ObserveCancellationAsync(Task.WhenAll(clients.Values));
        }

        return 0;
    }

    private static PosixSignalRegistration RegisterSignal(PosixSignal signal, CancellationTokenSource shutdown)
    {
        return PosixSignalRegistration.Create(signal, context =>
        {
            context.Cancel = true;
            shutdown.Cancel();
        });
    }

    private static async Task AcceptLoopAsync(
        TcpListener listener,
        RuntimeState state,
        ConcurrentDictionary<int, Task> clients,
        CancellationToken cancellationToken)
    {
        var clientId = 0;
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                var client = await listener.AcceptTcpClientAsync(cancellationToken);
                var id = Interlocked.Increment(ref clientId);
                var task = HandleClientAsync(client, state, cancellationToken);
                clients[id] = task;
                _ = task.ContinueWith(
                    completed =>
                    {
                        clients.TryRemove(id, out _);
                        if (completed.IsFaulted)
                        {
                            Console.Error.WriteLine(completed.Exception);
                        }
                    },
                    CancellationToken.None,
                    TaskContinuationOptions.ExecuteSynchronously,
                    TaskScheduler.Default);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (SocketException) when (cancellationToken.IsCancellationRequested)
        {
        }
    }

    private static async Task HandleClientAsync(TcpClient client, RuntimeState state, CancellationToken cancellationToken)
    {
        using (client)
        await using (var stream = client.GetStream())
        {
            var requestBuffer = new byte[4096];
            var bytesRead = await stream.ReadAsync(requestBuffer, cancellationToken);
            var request = Encoding.ASCII.GetString(requestBuffer, 0, bytesRead);
            var requestLine = request.Split("\r\n", 2, StringSplitOptions.None)[0].Split(' ');
            var path = requestLine.Length >= 2 ? requestLine[1].Split('?', 2)[0] : string.Empty;

            int statusCode;
            string reason;
            string body;
            if (path == "/internal")
            {
                statusCode = 200;
                reason = "OK";
                body = "{\"status\":\"dotnet-runtime-internal-ok\"}";
            }
            else if (path != "/")
            {
                statusCode = 404;
                reason = "Not Found";
                body = "{\"status\":\"not-found\"}";
            }
            else if (!state.Ready)
            {
                await state.WaitUntilReadyAsync(cancellationToken);
                if (!state.Ready)
                {
                    statusCode = 503;
                    reason = "Service Unavailable";
                    body = JsonSerializer.Serialize(new { status = "starting", checks = state.Checks.ToArray() });
                }
                else
                {
                    statusCode = 200;
                    reason = "OK";
                    body = JsonSerializer.Serialize(new { status = "dotnet-runtime-app-ok", checks = state.Checks.ToArray() });
                }
            }
            else
            {
                statusCode = 200;
                reason = "OK";
                body = JsonSerializer.Serialize(new { status = "dotnet-runtime-app-ok", checks = state.Checks.ToArray() });
            }

            var bodyBytes = Encoding.UTF8.GetBytes(body);
            var headers = Encoding.ASCII.GetBytes(
                $"HTTP/1.1 {statusCode} {reason}\r\n" +
                "Content-Type: application/json; charset=utf-8\r\n" +
                $"Content-Length: {bodyBytes.Length}\r\n" +
                "Connection: close\r\n\r\n");
            await stream.WriteAsync(headers, cancellationToken);
            await stream.WriteAsync(bodyBytes, cancellationToken);
        }
    }

    private static async Task RunStartupChecksAsync(ConcurrentQueue<string> checks)
    {
        var configPath = Environment.GetEnvironmentVariable("DHI_CONFIG_PATH") ?? "/app/appsettings.json";
        var fileConfig = JsonSerializer.Deserialize<AppConfig>(
            await File.ReadAllTextAsync(configPath, Encoding.UTF8),
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true })
            ?? throw new InvalidOperationException("configuration JSON was empty");
        var effectiveMode = Environment.GetEnvironmentVariable("DHI_APP_MODE") ?? fileConfig.Mode;
        Require(fileConfig.Mode == "file", "file configuration was not loaded");
        Require(effectiveMode == "environment", "environment did not override file configuration");
        Require(fileConfig.Label == "dotnet-runtime", "unexpected configuration label");
        checks.Enqueue("config-precedence");

        var json = JsonSerializer.Serialize(new JsonProbe("Zażółć ☃", 3));
        var roundTrip = JsonSerializer.Deserialize<JsonProbe>(json);
        Require(roundTrip == new JsonProbe("Zażółć ☃", 3), "JSON round trip failed");
        checks.Enqueue("json");

        var temporaryDirectory = Directory.CreateTempSubdirectory("dhi-dotnet-");
        try
        {
            var temporaryFile = Path.Combine(temporaryDirectory.FullName, "probe.txt");
            await File.WriteAllTextAsync(temporaryFile, "dotnet-filesystem-ok", Encoding.UTF8);
            Require(await File.ReadAllTextAsync(temporaryFile, Encoding.UTF8) == "dotnet-filesystem-ok", "temporary file mismatch");
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
            await gzip.WriteAsync(Encoding.UTF8.GetBytes("dotnet-compression-ok"));
        }
        compressed.Position = 0;
        using var decompressor = new GZipStream(compressed, CompressionMode.Decompress);
        using var decompressed = new StreamReader(decompressor, Encoding.UTF8);
        Require(await decompressed.ReadToEndAsync() == "dotnet-compression-ok", "gzip round trip failed");
        checks.Enqueue("compression");

        const string text = "Zażółć";
        Require(Encoding.UTF8.GetString(Encoding.UTF8.GetBytes(text)) == text, "UTF-8 round trip failed");
        Require(TimeZoneInfo.ConvertTime(DateTimeOffset.Parse("2020-01-01T00:00:00Z"), TimeZoneInfo.Utc).Offset == TimeSpan.Zero, "UTC timezone offset mismatch");
        checks.Enqueue("encoding-timezone");

        var workerResults = await Task.WhenAll(Enumerable.Range(1, 5).Select(number => Task.Run(() => number * number)));
        Require(workerResults.Sum() == 55, "thread-pool computation failed");
        checks.Enqueue("worker-threads");

        var method = typeof(Program).GetMethod(nameof(ReflectedChecksum), BindingFlags.NonPublic | BindingFlags.Static)
            ?? throw new InvalidOperationException("reflection target was not found");
        Require((int?)method.Invoke(null, new object[] { "dotnet" }) == 654, "reflection invocation failed");
        checks.Enqueue("reflection");

        Require(GetPid() == Environment.ProcessId, "native libc getpid mismatch");
        checks.Enqueue("native-libc");
    }

    private static async Task ProbeLocalHttpAsync()
    {
        using var handler = new SocketsHttpHandler { UseProxy = false };
        using var client = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(5) };
        var internalResponse = await client.GetAsync("http://127.0.0.1:8080/internal");
        Require(internalResponse.StatusCode == HttpStatusCode.OK, "local HTTP probe returned a non-200 status");
        Require((await internalResponse.Content.ReadAsStringAsync()).Contains("dotnet-runtime-internal-ok", StringComparison.Ordinal), "local HTTP probe returned the wrong body");

        var missingResponse = await client.GetAsync("http://127.0.0.1:8080/missing");
        Require(missingResponse.StatusCode == HttpStatusCode.NotFound, "routing negative probe did not return 404");
    }

    private static async Task ObserveCancellationAsync(Task task)
    {
        try
        {
            await task;
        }
        catch (OperationCanceledException)
        {
        }
    }

    private static int ReflectedChecksum(string value) => value.Sum(character => character);

    private static void Require(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }

    [DllImport("libc", EntryPoint = "getpid")]
    private static extern int GetPid();

    private sealed class RuntimeState
    {
        public volatile bool Ready;
        public ConcurrentQueue<string> Checks { get; } = new();
        private TaskCompletionSource<bool> ReadySignal { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public void MarkReady()
        {
            Ready = true;
            ReadySignal.TrySetResult(true);
        }

        public async Task WaitUntilReadyAsync(CancellationToken cancellationToken)
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

    private sealed record AppConfig(string Label, string Mode);
    private sealed record JsonProbe(string Text, int Count);
}
