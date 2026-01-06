"""
HTML View
Renders HTML templates
"""

from pathlib import Path
from fastapi.templating import Jinja2Templates
from fastapi import Request


class HtmlView:
    """HTML template renderer"""
    
    def __init__(self):
        template_path = Path(__file__).parent.parent.parent / "templates"
        if template_path.exists():
            self.templates = Jinja2Templates(directory=str(template_path))
        else:
            self.templates = None
    
    def render(self, request: Request, template_name: str, context: dict = None):
        """Render HTML template"""
        if not self.templates:
            return {"error": "Templates not configured"}
        
        ctx = context or {}
        ctx["request"] = request
        return self.templates.TemplateResponse(template_name, ctx)


# Global instance
html_view = HtmlView()
