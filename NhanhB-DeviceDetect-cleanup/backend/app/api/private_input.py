"""Redact request input from FastAPI validation errors."""

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute


class PrivateInputRoute(APIRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def validate(request):
            try:
                return await handle(request)
            except RequestValidationError:
                # FastAPI's default error includes the rejected request input.
                return JSONResponse({'detail': 'Dữ liệu yêu cầu không hợp lệ'}, status_code=422)

        return validate
