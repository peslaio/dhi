<?php
declare(strict_types=1);

spl_autoload_register(static function (string $class): void {
    $prefix = 'Dhi\\Functional\\';
    if (!str_starts_with($class, $prefix)) {
        return;
    }

    $relative = substr($class, strlen($prefix));
    $path = __DIR__ . '/src/' . str_replace('\\', '/', $relative) . '.php';
    if (is_file($path)) {
        require $path;
    }
});

function respond(int $status, array $payload): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES);
    exit;
}

$requiredExtensions = [
    'calendar',
    'ctype',
    'exif',
    'FFI',
    'fileinfo',
    'ftp',
    'gettext',
    'iconv',
    'PDO',
    'Phar',
    'posix',
    'readline',
    'shmop',
    'sockets',
    'sysvmsg',
    'sysvsem',
    'sysvshm',
    'tokenizer',
    'Zend OPcache',
];
$missingExtensions = array_values(array_filter(
    $requiredExtensions,
    static fn (string $extension): bool => !extension_loaded($extension),
));

$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

if ($path === '/') {
    respond($missingExtensions === [] ? 200 : 500, [
        'status' => $missingExtensions === [] ? 'php-fpm-app-ok' : 'missing-extensions',
        'sapi' => PHP_SAPI,
        'phpVersion' => PHP_VERSION,
        'extensions' => $requiredExtensions,
        'missingExtensions' => $missingExtensions,
        'opcacheLoaded' => extension_loaded('Zend OPcache'),
    ]);
}

if ($path === '/api/autoload' && $method === 'GET') {
    $value = new Dhi\Functional\ContractValue('autoload-ok');
    respond(200, ['value' => $value->normalized()]);
}

if ($path === '/api/query' && $method === 'GET') {
    respond(200, ['name' => (string) ($_GET['name'] ?? '')]);
}

if ($path === '/api/echo' && $method === 'POST') {
    try {
        $input = json_decode(file_get_contents('php://input'), true, 32, JSON_THROW_ON_ERROR);
    } catch (JsonException $error) {
        respond(400, ['error' => 'invalid-json']);
    }
    if (!is_array($input)) {
        respond(400, ['error' => 'json-object-required']);
    }
    respond(200, ['input' => $input]);
}

if ($path === '/api/session' && $method === 'GET') {
    session_name('DHISESSION');
    session_save_path(sys_get_temp_dir());
    if (!session_start([
        'cookie_httponly' => true,
        'cookie_samesite' => 'Strict',
        'use_strict_mode' => true,
    ])) {
        respond(500, ['error' => 'session-start-failed']);
    }
    $_SESSION['count'] = ((int) ($_SESSION['count'] ?? 0)) + 1;
    $count = $_SESSION['count'];
    session_write_close();
    respond(200, ['count' => $count]);
}

if ($path === '/api/upload' && $method === 'POST') {
    $upload = $_FILES['artifact'] ?? null;
    if (!is_array($upload) || ($upload['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK) {
        respond(400, ['error' => 'upload-required']);
    }
    $temporaryPath = (string) $upload['tmp_name'];
    respond(200, [
        'name' => (string) $upload['name'],
        'size' => filesize($temporaryPath),
        'sha256' => hash_file('sha256', $temporaryPath),
    ]);
}

if ($path === '/api/controlled-error' && $method === 'GET') {
    respond(422, ['error' => 'controlled-error']);
}

respond(404, ['error' => 'not-found']);
