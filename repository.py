class Repository:

    def __init__(self, model):
        self.model = model

    def get_all(self, db):
        return db.query(self.model).all()

    def get_by_id(self, db, item_id):
        return (
            db.query(self.model)
            .filter(self.model.id == item_id)
            .first()
        )

    def create(self, db, data: dict):
        try:
            obj = self.model(**data)

            db.add(obj)
            db.commit()
            db.refresh(obj)

            return obj

        except Exception:
            db.rollback()
            raise

    def update(self, db, item_id, data: dict):
        obj = self.get_by_id(db, item_id)

        if not obj:
            return None

        try:
            for key, value in data.items():
                setattr(obj, key, value)

            db.commit()
            db.refresh(obj)

            return obj

        except Exception:
            db.rollback()
            raise

    def delete(self, db, item_id):
        obj = self.get_by_id(db, item_id)

        if not obj:
            return False

        try:
            db.delete(obj)
            db.commit()

            return True

        except Exception:
            db.rollback()
            raise