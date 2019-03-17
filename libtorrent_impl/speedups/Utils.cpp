#include <cstdio>
#include <ctime>
#include <sys/time.h>

#include "Utils.hpp"

Logger::Level Logger::level = Logger::WARNING;

inline std::string Logger::get_level_name(Logger::Level level) {
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

void Logger::set_level(Level level) {
    Logger::level = level;
}

Logger::Logger(std::string name) : name(name) {
}

void Logger::log_va(Level level, const char *format, va_list args) {
    if (level < Logger::level) {
        return;
    }

    timeval now;
    if (gettimeofday(&now, NULL)) {
        throw std::runtime_error("Unable to call gettimeofday.");
    }
    tm now_tm;
    if (!localtime_r(&now.tv_sec, &now_tm)) {
        throw std::runtime_error("Unable to call localtime_r.");
    }
    char dt[64];
    strftime(dt, sizeof(dt) / sizeof(dt[0]), "%Y-%m-%d %H:%M:%S", &now_tm);

    fprintf(
            stderr,
            "%s,%0.3d - %s - %s - ",
            dt,
            now.tv_usec / 1000,
            this->name.c_str(),
            Logger::get_level_name(level).c_str()
    );
    vfprintf(stderr, format, args);
    fprintf(stderr, "\n");
}

void Logger::log(Level level, const char *format, ...) {
    if (level < Logger::level) {
        return;
    }
    va_list args;
    va_start(args, format);
    this->log_va(level, format, args);
    va_end(args);
}

void Logger::critical(const char *format, ...) {
    va_list args;
    va_start(args, format);
    this->log_va(Logger::CRITICAL, format, args);
    va_end(args);
}

void Logger::error(const char *format, ...) {
    va_list args;
    va_start(args, format);
    this->log_va(Logger::ERROR, format, args);
    va_end(args);
}

void Logger::warning(const char *format, ...) {
    va_list args;
    va_start(args, format);
    this->log_va(Logger::WARNING, format, args);
    va_end(args);
}

void Logger::info(const char *format, ...) {
    va_list args;
    va_start(args, format);
    this->log_va(Logger::INFO, format, args);
    va_end(args);
}

void Logger::debug(const char *format, ...) {
    va_list args;
    va_start(args, format);
    this->log_va(Logger::DEBUG, format, args);
    va_end(args);
}

double Timer::get_time() {
    timeval now;
    if (gettimeofday(&now, NULL)) {
        throw std::runtime_error("Unable to call gettimeofday.");
    }
    return now.tv_sec + now.tv_usec * 1.0e-6;
}

Timer::Timer() : start_time(-1), end_time(-1) {
}

void Timer::start() {
    if (this->start_time != -1 || this->end_time != -1) {
        throw std::runtime_error("Invalid timer state for start.");
    }
    this->start_time = Timer::get_time();
}

void Timer::stop() {
    if (this->start_time == -1 || this->end_time != -1) {
        throw std::runtime_error("Invalid timer state for end.");
    }
    this->end_time = Timer::get_time();
}

double Timer::total_seconds() {
    if (this->start_time == -1) {
        throw std::runtime_error("Trying to get total_seconds of a timer that's not started.");
    }
    if (this->end_time == -1) {
        return Timer::get_time() - this->start_time;
    } else {
        return this->end_time - this->start_time;
    }
}

bool Timer::is_stopped() {
    return this->end_time != -1;
}

AccumulatorTimer::AccumulatorTimer(
        TimerAccumulator *accumulator,
        std::string key)
        : accumulator(accumulator), key(key) {
}

AccumulatorTimer::~AccumulatorTimer() {
    if (!this->is_stopped()) {
        this->stop();
    }
}

void AccumulatorTimer::stop() {
    Timer::stop();
    auto item = this->accumulator->stats.emplace(this->key, TimerStat());
    item.first->second.count++;
    item.first->second.total_seconds += this->total_seconds();
}

TimerStat::TimerStat() : count(0), total_seconds(0) {
}

std::shared_ptr <AccumulatorTimer> TimerAccumulator::start_timer(std::string key) {
    auto timer_ptr = std::make_shared<AccumulatorTimer>(this, key);
    timer_ptr->start();
    return timer_ptr;
}
