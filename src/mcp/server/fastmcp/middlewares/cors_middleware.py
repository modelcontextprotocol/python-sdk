from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class CORSMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, allow_origins=None, allow_methods=None, allow_headers=None, max_age=None):
        super().__init__(app)
        self.allow_origins = allow_origins or ["*"]
        self.allow_methods = allow_methods or ["GET", "POST", "OPTIONS"]
        self.allow_headers = allow_headers or ["*"]
        self.max_age = max_age or "3600"

    async def dispatch(self, request: Request, call_next):
        # Handle OPTIONS method for CORS preflight requests
        if request.method == "OPTIONS":
            response = Response()
            response.headers["Access-Control-Allow-Origin"] = ",".join(self.allow_origins)
            response.headers["Access-Control-Allow-Methods"] = ",".join(self.allow_methods)
            response.headers["Access-Control-Allow-Headers"] = ",".join(self.allow_headers)
            response.headers["Access-Control-Max-Age"] = self.max_age
            return response

        # Process the request normally and then add CORS headers to the response
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = ",".join(self.allow_origins)
        response.headers["Access-Control-Allow-Methods"] = ",".join(self.allow_methods)
        response.headers["Access-Control-Allow-Headers"] = ",".join(self.allow_headers)
        return response
