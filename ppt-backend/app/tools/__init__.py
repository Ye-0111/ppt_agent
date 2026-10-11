"""LangChain 工具集 - 供 ChatService 绑定到大模型"""

from app.tools.file_tools import read_file, write_file, list_files
from app.tools.ppt_generator import generate_ppt
from app.tools.content_refiner import refine_content
from app.tools.chart_generator import add_chart_slide
from app.tools.enhance_ppt import enhance_ppt
from app.tools.pexels_search import add_image_slide
from app.tools.tavily_search import web_search, fetch_page
from app.tools.ppt_template import render_ppt_template

# 所有工具列表，供 bind_tools() 使用
all_tools = [
    read_file,
    write_file,
    list_files,
    generate_ppt,
    refine_content,
    add_chart_slide,
    add_image_slide,
    enhance_ppt,
    web_search,
    fetch_page,
    render_ppt_template,
]
