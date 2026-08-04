<?php
header('Content-Type: application/json');

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

if ($missingExtensions !== []) {
    http_response_code(500);
    echo json_encode([
        'status' => 'missing-extensions',
        'extensions' => $missingExtensions,
    ]);
    return;
}

echo json_encode([
    'status' => 'php-fpm-app-ok',
    'sapi' => PHP_SAPI,
    'extensions' => $requiredExtensions,
]);
