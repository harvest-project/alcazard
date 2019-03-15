#ifndef LOGGING_HPP_
#define LOGGING_HPP_

#include <string>
#include <sqlite3.h>

class Logger {
private:

    static int level;
    std::string name;

public:

    enum Level {
        CRITICAL = 50
        ERROR = 40
        WARNING = 30
        INFO = 20
        DEBUG = 10
    };

    static void set_level(Level level);

    Logger(std::string name);

    void log(Level level, const char *format, ...);

    void critical(const char *format, ...);

    void error(const char *format, ...);

    void info(const char *format, ...);

    void debug(const char *format, ...);
};

#endif
