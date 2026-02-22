#include <iostream>
#include <iterator>
#include <string>
#include <libtorrent/bdecode.hpp>

int main() {
    std::string input((std::istreambuf_iterator<char>(std::cin)),
                       std::istreambuf_iterator<char>());

    lt::error_code ec;
    int error_pos = 0;
    lt::bdecode_node ret = lt::bdecode(
        lt::span<char const>{input.data(), static_cast<int>(input.size())},
        ec, &error_pos);

    if (ec) return 1;

    // Trailing data check: bdecode stops after first complete value
    if (ret.data_section().size() != static_cast<int>(input.size()))
        return 1;

    // Soft error check: leading zeros, unsorted/duplicate dict keys
    char err_buf[256] = {};
    if (ret.has_soft_error(lt::span<char>{err_buf, sizeof(err_buf)}))
        return 1;

    return 0;
}
