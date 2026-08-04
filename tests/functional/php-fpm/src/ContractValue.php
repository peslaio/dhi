<?php
declare(strict_types=1);

namespace Dhi\Functional;

final class ContractValue
{
    public function __construct(private readonly string $value)
    {
    }

    public function normalized(): string
    {
        return strtoupper($this->value);
    }
}
