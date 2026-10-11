"""控制层包"""

from app.controller.user import router as user_router
from app.controller.chat import router as chat_router
from app.controller.ppt import router as ppt_router
from app.controller.ppt_template import router as template_router

__all__ = ["user_router", "chat_router", "ppt_router", "template_router"]