import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.lang.reflect.Method;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.HexFormat;
import java.util.List;
import java.util.Properties;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.zip.GZIPInputStream;
import java.util.zip.GZIPOutputStream;

public final class App {
    private static final List<String> CHECKS = new CopyOnWriteArrayList<>();
    private static final AtomicBoolean READY = new AtomicBoolean(false);
    private static final CountDownLatch READY_LATCH = new CountDownLatch(1);

    private App() {}

    public static void main(String[] args) throws Exception {
        runStartupChecks();

        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", 8080), 0);
        ExecutorService httpExecutor = Executors.newFixedThreadPool(4);
        server.setExecutor(httpExecutor);
        server.createContext("/internal", exchange -> sendJson(exchange, 200, "{\"status\":\"java-internal-ok\"}"));
        server.createContext("/", App::handleRoot);

        CountDownLatch shutdown = new CountDownLatch(1);
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            READY.set(false);
            server.stop(1);
            httpExecutor.shutdownNow();
            shutdown.countDown();
        }, "shutdown-hook"));

        try {
            server.start();
            probeLocalHttp();
            CHECKS.add("local-http");
            READY.set(true);
            READY_LATCH.countDown();
            System.out.println("java startup checks passed: " + String.join(",", CHECKS));
            shutdown.await();
        } catch (Exception exception) {
            READY.set(false);
            server.stop(0);
            httpExecutor.shutdownNow();
            throw exception;
        }
    }

    private static void handleRoot(HttpExchange exchange) throws IOException {
        if (!"/".equals(exchange.getRequestURI().getPath())) {
            sendJson(exchange, 404, "{\"status\":\"not-found\"}");
            return;
        }

        if (!READY.get()) {
            try {
                READY_LATCH.await(5, TimeUnit.SECONDS);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
            }
            if (!READY.get()) {
                sendJson(exchange, 503, responseJson("starting"));
                return;
            }
        }

        sendJson(exchange, 200, responseJson("java-app-ok"));
    }

    private static void runStartupChecks() throws Exception {
        Path configPath = Path.of(System.getenv().getOrDefault("DHI_CONFIG_PATH", "/app/app.properties"));
        Properties fileConfig = new Properties();
        try (var input = Files.newInputStream(configPath)) {
            fileConfig.load(input);
        }
        String fileMode = fileConfig.getProperty("mode");
        String effectiveMode = System.getenv().getOrDefault("DHI_APP_MODE", fileMode);
        require("file".equals(fileMode), "file configuration was not loaded");
        require("environment".equals(effectiveMode), "environment did not override file configuration");
        require("java-runtime".equals(fileConfig.getProperty("label")), "unexpected configuration label");
        CHECKS.add("config-precedence");

        String escaped = jsonEscape("Zażółć \"snow\" \\ path");
        require("Zażółć \\\"snow\\\" \\\\ path".equals(escaped), "JSON escaping failed");
        CHECKS.add("json");

        Path temporaryDirectory = Files.createTempDirectory(Path.of("/tmp"), "dhi-java-");
        Path temporaryFile = temporaryDirectory.resolve("probe.txt");
        try {
            Files.writeString(temporaryFile, "java-filesystem-ok", StandardCharsets.UTF_8);
            require("java-filesystem-ok".equals(Files.readString(temporaryFile, StandardCharsets.UTF_8)), "temporary file mismatch");
        } finally {
            Files.deleteIfExists(temporaryFile);
            Files.deleteIfExists(temporaryDirectory);
        }
        CHECKS.add("filesystem-tmp");

        require(InetAddress.getAllByName("localhost").length > 0, "localhost DNS lookup returned no addresses");
        CHECKS.add("dns");

        byte[] digest = MessageDigest.getInstance("SHA-256").digest("abc".getBytes(StandardCharsets.UTF_8));
        require("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad".equals(HexFormat.of().formatHex(digest)), "SHA-256 mismatch");
        CHECKS.add("crypto");

        ByteArrayOutputStream compressedBuffer = new ByteArrayOutputStream();
        try (GZIPOutputStream gzip = new GZIPOutputStream(compressedBuffer)) {
            gzip.write("java-compression-ok".getBytes(StandardCharsets.UTF_8));
        }
        String decompressed;
        try (GZIPInputStream gzip = new GZIPInputStream(new ByteArrayInputStream(compressedBuffer.toByteArray()))) {
            decompressed = new String(gzip.readAllBytes(), StandardCharsets.UTF_8);
        }
        require("java-compression-ok".equals(decompressed), "gzip round trip failed");
        CHECKS.add("compression");

        String text = "Zażółć";
        require(text.equals(new String(text.getBytes(StandardCharsets.UTF_8), StandardCharsets.UTF_8)), "UTF-8 round trip failed");
        ZonedDateTime utc = ZonedDateTime.ofInstant(Instant.parse("2020-01-01T00:00:00Z"), ZoneId.of("UTC"));
        require(utc.getOffset().getTotalSeconds() == 0, "UTC timezone offset mismatch");
        CHECKS.add("encoding-timezone");

        ExecutorService workers = Executors.newFixedThreadPool(3);
        try {
            List<Future<Integer>> futures = List.of(
                    workers.submit(() -> 1 * 1 + 2 * 2),
                    workers.submit(() -> 3 * 3),
                    workers.submit(() -> 4 * 4 + 5 * 5));
            int sum = 0;
            for (Future<Integer> future : futures) {
                sum += future.get();
            }
            require(sum == 55, "executor computation failed");
        } finally {
            workers.shutdownNow();
        }
        CHECKS.add("worker-threads");

        Method method = App.class.getDeclaredMethod("reflectedChecksum", String.class);
        method.setAccessible(true);
        require(((Integer) method.invoke(null, "java")) == 418, "reflection invocation failed");
        CHECKS.add("reflection");

        require(ProcessHandle.current().pid() > 0, "native process sentinel returned an invalid pid");
        CHECKS.add("native-process");
    }

    private static void probeLocalHttp() throws Exception {
        HttpClient client = HttpClient.newBuilder().build();
        HttpRequest request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:8080/internal")).GET().build();
        HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        require(response.statusCode() == 200, "local HTTP probe returned a non-200 status");
        require(response.body().contains("java-internal-ok"), "local HTTP probe returned the wrong body");

        HttpRequest missingRequest = HttpRequest.newBuilder(URI.create("http://127.0.0.1:8080/missing")).GET().build();
        HttpResponse<String> missingResponse = client.send(missingRequest, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        require(missingResponse.statusCode() == 404, "routing negative probe did not return 404");
    }

    private static int reflectedChecksum(String value) {
        return value.chars().sum();
    }

    private static String responseJson(String status) {
        String checks = CHECKS.stream().map(value -> "\"" + jsonEscape(value) + "\"").reduce((left, right) -> left + "," + right).orElse("");
        return "{\"status\":\"" + jsonEscape(status) + "\",\"checks\":[" + checks + "]}";
    }

    private static String jsonEscape(String value) {
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    private static void sendJson(HttpExchange exchange, int statusCode, String body) throws IOException {
        byte[] response = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(statusCode, response.length);
        try (var output = exchange.getResponseBody()) {
            output.write(response);
        }
    }

    private static void require(boolean condition, String message) {
        if (!condition) {
            throw new IllegalStateException(message);
        }
    }
}
