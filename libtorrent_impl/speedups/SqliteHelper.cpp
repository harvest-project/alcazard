#include "SqliteHelper.hpp"

#include <cstdio>

SqliteStatement::SqliteStatement(sqlite3 *db, std::string query) : db(db), ptr(0) {
    SQLITE_CHECK(sqlite3_prepare_v2(this->db, query.c_str(), -1, &this->ptr, NULL));
}

SqliteStatement::~SqliteStatement() {
    // Swallow errors because of no exceptions in destructor
    sqlite3_finalize(this->ptr);
    this->ptr = NULL;
}

bool SqliteStatement::step() {
    int result = sqlite3_step(this->ptr);
    if (result == SQLITE_DONE) {
        return false;
    } else if (result == SQLITE_ROW) {
        return true;
    } else {
        SQLITE_THROW();
    }
}

void SqliteStatement::reset() {
    SQLITE_CHECK(sqlite3_reset(this->ptr));
}

void SqliteStatement::clear_bindings() {
    SQLITE_CHECK(sqlite3_clear_bindings(this->ptr));
}

void SqliteStatement::bind_int(int col, int value) {
    SQLITE_CHECK(sqlite3_bind_int(this->ptr, col, value));
}

void SqliteStatement::bind_int64(int col, int64_t value) {
    SQLITE_CHECK(sqlite3_bind_int64(this->ptr, col, value));
}

void SqliteStatement::bind_blob(int col, std::string value) {
    throw std::runtime_error("Not implemented");
}

bool SqliteStatement::get_is_null(int col) {
    return sqlite3_column_type(this->ptr, col) == SQLITE_NULL;
}

int64_t SqliteStatement::get_int64(int col) {
    return sqlite3_column_int64(this->ptr, col);
}

std::string SqliteStatement::get_text(int col) {
    int length = sqlite3_column_bytes(this->ptr, col);
    if (!length) return "";
    return std::string((char *) sqlite3_column_text(this->ptr, col), length);
}

std::string SqliteStatement::get_blob(int col) {
    int length = sqlite3_column_bytes(this->ptr, col);
    if (!length) return "";
    return std::string((char *) sqlite3_column_blob(this->ptr, col), length);
}
