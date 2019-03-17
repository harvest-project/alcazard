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
    inline static std::string get_level_name(Level level);

private:
    static Level level;
    std::string name;

public:
    Logger(std::string name);

    void log_va(Level level, const char *format, va_list);
    void log(Level level, const char *format, ...);
    void critical(const char *format, ...);
    void error(const char *format, ...);
    void warning(const char *format, ...);
    void info(const char *format, ...);
    void debug(const char *format, ...);
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
