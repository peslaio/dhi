var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();

app.MapGet("/", () => Results.Json(new { status = "dotnet-aspnet-app-ok" }));
app.Run();
