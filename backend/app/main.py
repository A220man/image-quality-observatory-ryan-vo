"""Application factory; runtime resources belong to the application lifespan."""
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from app.api.routes import router
from app.core.auth import OIDCClient, router as auth_router
from app.core.config import Settings, ensure_db_dir, load_settings, validate_settings
from app.core.db import Database
from app.core.errors import install_error_handlers
from app.services.catalog import Catalog


class BodyTooLarge(HTTPException):
    def __init__(self):
        super().__init__(413, 'Request body exceeds configured size limit')


class BodyLimit:
    def __init__(self, app, maximum: int):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        consumed = 0
        started = False

        async def bounded_receive():
            nonlocal consumed
            message = await receive()
            if message['type'] == 'http.request':
                consumed += len(message.get('body', b''))
                if consumed > self.maximum:raise BodyTooLarge()
            return message

        async def track_send(message):
            nonlocal started
            if message['type'] == 'http.response.start':started = True
            await send(message)

        try:await self.app(scope, bounded_receive, track_send)
        except BodyTooLarge:
            if started:raise
            response = JSONResponse(status_code=413, content={'error': {
                'code': 'request_limit', 'message': 'Request body exceeds configured size limit'}})
            await response(scope, receive, send)


def create_app(settings: Settings | None = None, oidc_transport: httpx.BaseTransport | None = None) -> FastAPI:
    settings = settings or load_settings()
    validate_settings(settings)

    @asynccontextmanager
    async def lifespan(app):
        ensure_db_dir(settings.database_path)
        db = Database(settings.database_path)
        app.state.db = db
        app.state.catalog = Catalog(db)
        app.state.oidc = OIDCClient(settings, transport=oidc_transport)
        try:yield
        finally:db.close()

    app = FastAPI(title='Image Quality Observatory', version='1.0.0', lifespan=lifespan)
    app.state.settings = settings
    install_error_handlers(app)
    app.add_middleware(BodyLimit, maximum=settings.max_upload_bytes+65536)
    app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url], allow_credentials=True,
                       allow_methods=['GET','POST','PATCH','PUT','DELETE'], allow_headers=['Content-Type','X-CSRF-Token'])
    app.include_router(auth_router)
    app.include_router(router)
    return app
