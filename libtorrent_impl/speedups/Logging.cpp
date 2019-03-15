#include <cstdarg>

#include "Logging.hpp"

const int Logger::level;

Logger::set_level(Level level)
{
    Logger::level = level;
}

Logger::Logger(std::string name) : name(name)
{
}

void Logger::log(Level level, const char *format, ...)
{
    va_list args;
    va_start(args, format);
    vfprintf(stream, format, args);
    va_end (args);
}
