from hannah.models.query import Query
import json

class BaseModel:
    __slots__ = ("_db",)
    __table__ = None
    # Kann nun ein String "id" oder eine Liste ["client_id", "feature_name"] sein
    __primary_key__ = "id"
    __json_fields__ = ()  # Spalten, die als JSON-String gespeichert werden

    def __init__(self, row=None, db=None, **extra):
        self._db = db
        if row is not None:
            if not isinstance(row, dict):
                row = dict(row)

            for attr in self.__slots__:
                if attr != "_db" and attr in row:
                    value = row.get(attr)
                    if attr in self.__json_fields__ and isinstance(value, str):
                        value = json.loads(value)
                    setattr(self, attr, value)

        for key, value in extra.items():
            setattr(self, key, value)

        self.after_init()

    @property
    def pk_values(self):
        """Gibt ein Dictionary mit allen PK-Spalten und deren aktuellen Werten zurück."""
        pk_cols = self.__primary_key__
        if isinstance(pk_cols, str):
            pk_cols = [pk_cols]
        
        return {col: getattr(self, col, None) for col in pk_cols}

    @property
    def pk_filter(self):
        """Hilfsmethode, um die WHERE-Clause und Parameter für PKs zu generieren."""
        pks = self.pk_values
        where_sql = " AND ".join([f"{col} = ?" for col in pks.keys()])
        return where_sql, list(pks.values())
    
    # -----------------------------
    # Core Query Builder
    # -----------------------------
    
    @classmethod
    def select(cls, db):
        return Query(cls, db)

    # -----------------------------
    # High-Level API
    # -----------------------------

    @classmethod
    def filter(cls, db, joins=None, **kwargs):
        return cls.select(db).join_list(joins).where(**kwargs).all()

    @classmethod
    def get(cls, db, joins=None, **kwargs):
        return cls.select(db).join_list(joins).where(**kwargs).first()

    @classmethod
    def get_or_404(cls, db, joins=None, **kwargs):
        return cls.select(db).join_list(joins).where(**kwargs).one_or_404()
    
    @classmethod
    def count(cls, db, where=None, params=None):
        sql = f"SELECT COUNT(*) FROM {cls.__table__}"
        if where:
            sql += f" WHERE {where}"
        return db.execute(sql, params or []).fetchone()[0]

    # -----------------------------
    # Helper
    # -----------------------------

    @classmethod
    def filter_by_ids(cls, db, ids, status=None, order_by=None):
        # Hinweis: filter_by_ids funktioniert logischerweise nur bei Single-PKs sinnvoll
        if not ids or isinstance(cls.__primary_key__, list):
            return []
        
        query = cls.select(db).where_in(cls.__primary_key__, ids)
        if status:
            query.where(status=status)
        if order_by:
            query.order_by(order_by)
        return query.all()
    
    @classmethod
    def create(cls, db, **kwargs):
        columns = []
        values = []
        for key, value in kwargs.items():
            if key in cls.__slots__ and not key.startswith('_'):
                columns.append(key)
                
                # NEU: Überprüfung auf Liste oder Dictionary
                if isinstance(value, (list, dict)):
                    values.append(json.dumps(value)) # In JSON-String umwandeln
                else:
                    values.append(value)

        if not columns:
            raise ValueError(f"Keine gültigen Felder für {cls.__name__} angegeben.")

        column_names = ", ".join(columns)
        placeholders = ", ".join(["?"] * len(columns))
        sql = f"INSERT INTO {cls.__table__} ({column_names}) VALUES ({placeholders})"
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"DATABASE QUERY: {sql} | PARAMS: {values}")
        cursor = db.execute(sql, values)
        db.commit()

        pk_cols = cls.__primary_key__
        if isinstance(pk_cols, str):
            pk_filter = {pk_cols: kwargs.get(pk_cols) or cursor.lastrowid}
        else:
            pk_filter = {col: kwargs.get(col) for col in pk_cols}
        
        return cls.get(db, **pk_filter)
    
    def update(self, **kwargs):
        if not self._db:
            raise AttributeError("Keine Datenbankverbindung vorhanden.")

        updates = []
        params = []
        
        pk_cols = self.__primary_key__
        if isinstance(pk_cols, str): pk_cols = [pk_cols]

        for key, value in kwargs.items():
            if key in self.__slots__ and key not in pk_cols and not key.startswith('_'):
                updates.append(f"{key} = ?")
                params.append(json.dumps(value) if isinstance(value, (list, dict)) else value)
                setattr(self, key, value)

        if not updates:
            return

        where_sql, pk_params = self.pk_filter
        params.extend(pk_params)
        
        sql = f"UPDATE {self.__table__} SET {', '.join(updates)} WHERE {where_sql}"
        self._db.execute(sql, params)
        self._db.commit()
        return self

    def save(self):
        pk_cols = self.__primary_key__
        if isinstance(pk_cols, str): pk_cols = [pk_cols]

        data = {attr: getattr(self, attr) for attr in self.__slots__ 
                if attr not in pk_cols and not attr.startswith('_')}
        return self.update(**data)

    def delete(self):
        if not self._db:
            raise AttributeError("Objekt kann nicht gelöscht werden (keine DB).")

        where_sql, pk_params = self.pk_filter
        sql = f"DELETE FROM {self.__table__} WHERE {where_sql}"
        self._db.execute(sql, pk_params)
        self._db.commit()
    
    def after_init(self):
        pass

    def to_dict(self, exclude=None):
        exclude = exclude or []
        result = {}
        for slot in self.__slots__:
            if slot.startswith('_') or slot in exclude:
                continue
            val = getattr(self, slot, None)
            if hasattr(val, 'to_dict'): continue 
            result[slot] = val
        return result