using System.Net;
using System.Net.Sockets;
using System.Text;

var listener = new TcpListener(IPAddress.Any, 8080);
listener.Start();

while (true)
{
    var client = await listener.AcceptTcpClientAsync();
    _ = Task.Run(async () =>
    {
        await using var stream = client.GetStream();
        var request = new byte[4096];
        await stream.ReadAsync(request);
        var body = "{\"status\":\"dotnet-runtime-app-ok\"}";
        var bodyBytes = Encoding.UTF8.GetBytes(body);
        var headers = Encoding.ASCII.GetBytes(
            $"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {bodyBytes.Length}\r\nConnection: close\r\n\r\n"
        );
        await stream.WriteAsync(headers);
        await stream.WriteAsync(bodyBytes);
        client.Dispose();
    });
}
