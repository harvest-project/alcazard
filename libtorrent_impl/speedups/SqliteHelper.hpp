#ifndef SQLITE_HELPER_HPP_
#define SQLITE_HELPER_HPP_

#include <string>
#include <sqlite3.h>

#define SQLITE_THROW() throw std::runtime_error(std::string(sqlite3_errmsg(this->db)))
#define SQLITE_CHECK(stmt) { if ((stmt) != SQLITE_OK) { SQLITE_THROW(); } }

class SqliteStatement {
public:
    sqlite3 *db;
    sqlite3_stmt *ptr;

    SqliteStatement(sqlite3 *db, std::string query);
    ~SqliteStatement();

    bool step();
    void reset();
    int update();
    int64_t insert();
    void exec_delete();

    void clear_bindings();
    void bind_int(int col, int value);
    void bind_int64(int col, int64_t value);
    void bind_text(int col, std::string value);
    void bind_blob(int col, std::string value);

    bool get_is_null(int col);
    int64_t get_int64(int col);
    std::string get_text(int col);
    std::string get_blob(int col);
};

#endif
