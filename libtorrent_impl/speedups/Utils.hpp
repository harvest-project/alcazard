#ifndef UTILS_HPP_
#define UTILS_HPP_

#include <cstdarg>
#include <string>
#include <unordered_map>

class Logger {
public:
    enum Level {
        CRITICAL = 50,
        ERROR = 40,
        WARNING = 30,
        INFO = 20,
        DEBUG = 10
    };

    static void set_level(Level level);

    inline static std::string get_level_name(Level level) {
        switch (level) {
            case Logger::CRITICAL:
                return "CRITICAL";
            case Logger::ERROR:
                return "ERROR";
            case Logger::WARNING:
                return "WARNING";
            case Logger::INFO:
                return "INFO";
            case Logger::DEBUG:
                return "DEBUG";
            default:
                throw std::runtime_error("Unknown level");
        }
    }

private:
    static Level level;
    std::string name;

public:
    Logger(std::string name);

    inline bool is_enabled_for(Level level) {
        return level >= this->level;
    }

    void log_va(Level level, const char *format, va_list);

    inline void log(Level level, const char *format, ...) {
        if (!this->is_enabled_for(level)) {
            return;
        }

        va_list args;
        va_start(args, format);
        this->log_va(level, format, args);
        va_end(args);
    }

    inline void critical(const char *format, ...) {
        va_list args;
        va_start(args, format);
        this->log_va(Logger::ERROR, format, args);
        va_end(args);
    }

    inline void error(const char *format, ...) {
        va_list args;
        va_start(args, format);
        this->log_va(Logger::ERROR, format, args);
        va_end(args);
    }

    inline void warning(const char *format, ...) {
        va_list args;
        va_start(args, format);
        this->log_va(Logger::WARNING, format, args);
        va_end(args);
    }

    inline void info(const char *format, ...) {
        va_list args;
        va_start(args, format);
        this->log_va(Logger::INFO, format, args);
        va_end(args);
    }

    inline void debug(const char *format, ...) {
        va_list args;
        va_start(args, format);
        this->log_va(Logger::DEBUG, format, args);
        va_end(args);
    }
};

class Timer {
public:
    static double get_time();

private:
    double start_time;
    double end_time;
public:
    Timer();
    void start();
    virtual void stop();
    double total_seconds();
    bool is_stopped();
};

class TimerAccumulator;

class AccumulatorTimer : public Timer {
private:
    TimerAccumulator *accumulator;
    std::string key;

public:
    AccumulatorTimer(TimerAccumulator *accumulator, std::string key);
    virtual ~AccumulatorTimer();
    virtual void stop();
};

struct TimerStat {
    int count;
    double total_seconds;

    TimerStat();
};

typedef std::unordered_map <std::string, TimerStat> TimerStats;

class TimerAccumulator {
public:
    TimerStats stats;
    std::shared_ptr <AccumulatorTimer> start_timer(std::string key);
};

#endif
