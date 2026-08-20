class Repository:
    def __init__(self, model):
        self.model = model

    def get_all(self, db):
        return db.query(self.model).all()

    def get_by_id(self, db, item_id):
        return db.query(self.model).filter(self.model.id == item_id).first()

    def create(self, db, data: dict):
        obj = self.model(**data)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def update(self, db, item_id, data: dict):
        obj = self.get_by_id(db, item_id)
        if not obj:
            return None
        for key, value in data.items():
            setattr(obj, key, value)
        db.commit()
        db.refresh(obj)
        return obj

    def delete(self, db, item_id):
        obj = self.get_by_id(db, item_id)
        if not obj:
            return False
        db.delete(obj)
        db.commit()
        return True
