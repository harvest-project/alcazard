#include <cstdio>
#include <ctime>
#include <sys/time.h>
#include <memory>
#include <stdexcept>
#include "Utils.hpp"

Logger::Level Logger::level = Logger::WARNING;

void Logger::set_level(Level level) {
    Logger::level = level;
}

Logger::Logger(std::string name) : name(name) {
}

void Logger::log_va(Level level, const char *format, va_list args) {
    if (!this->is_enabled_for(level)) {
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
            "%s,%03lu - %s - %s - ",
            dt,
            now.tv_usec / 1000,
            this->name.c_str(),
            Logger::get_level_name(level).c_str()
    );
    vfprintf(stderr, format, args);
    fprintf(stderr, "\n");
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
