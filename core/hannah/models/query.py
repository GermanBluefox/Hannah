import logging

logger = logging.getLogger(__name__)

class Query:
    def __init__(self, model, db):
        self.model = model
        self.db = db
        self._fields = f"{self.model.__table__}.*"
        self._where_clauses = []
        self._params = []
        self._order_by = None
        self._limit = None
        self._joins = []

    def where(self, *args, **kwargs):
        """Erlaubt Chaining: .where(status='online') oder .where("cg.client_id = ?", id)"""
        if args:
            self._where_clauses.append(args[0])
            self._params.extend(args[1:])
        for key, value in kwargs.items():
            if value is None:
                self._where_clauses.append(f"{self.model.__table__}.{key} IS NULL")
            else:
                self._where_clauses.append(f"{self.model.__table__}.{key} = ?")
                self._params.append(value)
        return self
    
    def where_in(self, column, values):
        """Erlaubt: .where_in('id', [1, 2, 3])"""
        if not values:
            self._where_clauses.append("1 = 0") 
            return self

        placeholders = ", ".join(["?"] * len(values))
        self._where_clauses.append(f"{self.model.__table__}.{column} IN ({placeholders})")
        self._params.extend(values)
        return self

    def order_by(self, column):
        self._order_by = column
        return self

    def limit(self, count):
        self._limit = count
        return self

    def join(self, table_or_sql, on=None):
        self._joins.append(f"JOIN {table_or_sql} ON {on}")
        return self

    def join_list(self, joins):
        """Verarbeitet eine Liste von Join-Strings (für Abwärtskompatibilität)."""
        if joins:
            for j in joins:
                self.join(j)
        return self
    
    def fields(self, field_string):
        """Erlaubt: .fields("id, name, status")"""
        self._fields = field_string
        return self
    
    def _build_sql(self):
        """Generiert den finalen SQL-String erst kurz vor der Ausführung."""
        sql = f"SELECT {self._fields} FROM {self.model.__table__}"
        
        if self._joins:
            sql += " " + " ".join(self._joins)
        
        if self._where_clauses:
            sql += " WHERE " + " AND ".join(self._where_clauses)
            
        if self._order_by:
            sql += f" ORDER BY {self._order_by}"
            
        if self._limit:
            sql += f" LIMIT {self._limit}"
            
        logger.debug(f"DATABASE QUERY: {sql} | PARAMS: {self._params}")
        return sql

    def all(self):
        sql = self._build_sql()
        rows = self.db.execute(sql, self._params).fetchall()
        return [self.model(row, db=self.db) for row in rows]

    def first(self):
        self.limit(1)
        sql = self._build_sql()
        row = self.db.execute(sql, self._params).fetchone()
        return self.model(row, db=self.db) if row else None

    def one_or_404(self):
        row = self.first()
        if not row:
            raise LookupError(f"{self.model.__name__} not found")
        return row