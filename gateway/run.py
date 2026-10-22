from opensms_gateway.app import create_app
from opensms_gateway.config import GatewaySettings

settings = GatewaySettings.from_env()
app = create_app(settings=settings)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
