from app import create_app
from app.tasks import celery
from app.models import db

app = create_app()
app.app_context().push()
