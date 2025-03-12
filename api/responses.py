from rest_framework.response import Response
from rest_framework import status

class ApiResponse:
    def __init__(self, status="success", message="", data=None, errors=None):
        self.status = status
        self.message = message
        self.data = data
        self.errors = errors  # Added errors field

    def to_response(self, http_status=status.HTTP_200_OK):
        return Response({
            "status": self.status,
            "message": self.message,
            "data": self.data,
            "errors": self.errors  # Return errors in response
        }, status=http_status)

    @staticmethod
    def error(message="An error occurred", errors=None, http_status=status.HTTP_400_BAD_REQUEST):
        return Response({
            "status": "error",
            "message": message,
            "data": None,
            "errors": errors
        }, status=http_status)
