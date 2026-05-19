import gradio as gr
import os
import subprocess
import time
import shutil
import datetime
import re

# Thay đổi working directory về thư mục gốc của project
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

def create_mock_svg(filepath, title="MOCK SLIDE", subtitle="Generated for Demo", image_path=None):
    # Calculate image tag if image_path is provided
    img_tag = ""
    if image_path:
        # We need a relative path from svg_output to images directory
        rel_image_path = f"../images/{os.path.basename(image_path)}"
        img_tag = f'<image href="{rel_image_path}" x="180" y="420" width="300" height="150" preserveAspectRatio="xMidYMid slice" />'
        
    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">
    <rect width="1280" height="720" fill="#f0f4f8" />
    <!-- Header background -->
    <rect x="0" y="0" width="1280" height="120" fill="#2c3e50" />
    <text x="640" y="80" font-family="Arial" font-size="48" font-weight="bold" fill="#ffffff" text-anchor="middle">{title}</text>
    
    <!-- Main content box -->
    <rect x="140" y="200" width="1000" height="400" rx="20" fill="#ffffff" />
    <text x="640" y="320" font-family="Arial" font-size="36" fill="#34495e" text-anchor="middle">{subtitle}</text>
    {img_tag}
    <!-- Footer -->
    <text x="640" y="680" font-family="Arial" font-size="20" fill="#7f8c8d" text-anchor="middle">PPT Master - AI Generated Mock</text>
</svg>"""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(svg_content)

def clean_svg_content(content):
    """Làm sạch output từ LLM để lấy code SVG thuần"""
    if "```" in content:
        # Tìm block code SVG
        matches = re.findall(r'```(?:xml|svg)?\n(.*?)\n```', content, re.DOTALL)
        if matches:
            content = matches[0]
        else:
            # Xóa các markdown tick
            content = re.sub(r'```(?:xml|svg)?\n', '', content)
            content = content.replace('```', '')
    return content.strip()

def generate_svg_with_llm(topic, slide_num, total_slides, api_key, filepath):
    prompt = f"""You are an expert presentation designer. Create a professional SVG slide (1280x720) for a presentation about '{topic}'.
This is slide {slide_num} out of {total_slides}.
Rules:
1. Canvas must be 1280x720: <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">
2. Use modern, beautiful design with good contrast.
3. STRICT SVG LIMITATIONS: DO NOT use <style>, <foreignObject>, mask, class, textPath. Use inline attributes only (fill="#xx", font-size="20").
4. Return ONLY the raw XML <svg>...</svg> code. Do not include any explanations.
"""
    
    try:
        if api_key.startswith("sk-"):
            # Sử dụng OpenAI
            import openai
            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            svg_content = response.choices[0].message.content
        else:
            # Giả định là Gemini
            from google import genai
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model='gemini-2.5-pro',
                contents=prompt,
            )
            svg_content = response.text
            
        svg_content = clean_svg_content(svg_content)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(svg_content)
        return True
    except Exception as e:
        print(f"LLM Error: {e}")
        return False

def generate_ppt(topic, uploaded_files, num_slides=3, api_key=""):
    # Tạo tên project ngẫu nhiên dựa trên timestamp
    timestamp = datetime.datetime.now().strftime("%Y%md_%H%M%S")
    project_name = f"demo_project_{timestamp}"
    project_path = os.path.join(PROJECT_ROOT, "projects", project_name)
    
    yield f"🚀 Đang khởi tạo project: {project_name}...", None
    time.sleep(1)
    
    # Bước 1: Khởi tạo Project (sử dụng script project_manager.py)
    init_cmd = ["python3", "skills/ppt-master/scripts/project_manager.py", "init", project_name, "--format", "ppt169"]
    result = subprocess.run(init_cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        yield f"❌ Lỗi khi khởi tạo project:\n{result.stderr}", None
        return
        
    yield "✅ Đã tạo project thành công. Đang xử lý file upload...", None
    
    # Bước 1.5: Xử lý file upload
    first_image = None
    if uploaded_files:
        file_paths = [f.name for f in uploaded_files]
        import_cmd = ["python3", "skills/ppt-master/scripts/project_manager.py", "import-sources", project_path] + file_paths + ["--copy"]
        import_result = subprocess.run(import_cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
        
        # Thử tìm một ảnh đã được import để làm mock
        images_dir = os.path.join(project_path, "images")
        if os.path.exists(images_dir):
            images = [f for f in os.listdir(images_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
            if images:
                first_image = os.path.join(images_dir, images[0])
                
        yield f"✅ Đã import {len(uploaded_files)} file. Đang sinh slide...", None
    else:
        yield "✅ Không có file upload. Đang sinh slide...", None
    
    # Bước 2: Sinh file SVG
    svg_out_dir = os.path.join(project_path, "svg_output")
    os.makedirs(svg_out_dir, exist_ok=True)
    
    use_llm = bool(api_key.strip())
    if use_llm:
        yield "🧠 Đã nhận diện API Key! Đang kết nối với AI Model để sinh thiết kế...", None
        
    for i in range(1, int(num_slides) + 1):
        svg_file = os.path.join(svg_out_dir, f"{i:02d}_slide.svg")
        
        if use_llm:
            yield f"⏳ Đang dùng AI để sinh Slide {i}/{int(num_slides)}...", None
            success = generate_svg_with_llm(topic, i, int(num_slides), api_key.strip(), svg_file)
            if not success:
                yield f"⚠️ Lỗi khi gọi AI ở Slide {i}, chuyển về dùng slide mặc định.", None
                create_mock_svg(svg_file, f"Lỗi AI Slide {i}", "Vui lòng kiểm tra lại API Key")
        else:
            # Fallback to mock
            image_for_slide = None
            if i == 1:
                title = topic if topic.strip() else "Slide Tiêu Đề"
                subtitle = "Trình bày: AI Agent"
            else:
                title = f"Nội dung Slide {i}"
                subtitle = f"Đây là nội dung chi tiết cho trang số {i} của chủ đề {topic}"
                if first_image and i == 2:
                    image_for_slide = first_image
                    subtitle += " (Có chèn ảnh minh hoạ)"
                
            create_mock_svg(svg_file, title, subtitle, image_path=image_for_slide)
        
    # Tạo speaker notes giả lập
    notes_dir = os.path.join(project_path, "notes")
    os.makedirs(notes_dir, exist_ok=True)
    with open(os.path.join(notes_dir, "total.md"), "w", encoding="utf-8") as f:
        for i in range(1, int(num_slides) + 1):
            f.write(f"# Page {i}\nĐây là ghi chú (speaker notes) cho slide số {i}.\n\n")
            
    yield "✅ Đã sinh xong SVG. Bắt đầu quá trình Hậu kiểm (Post-processing)...", None
    
    # Bước 3: Chạy Post-processing
    yield "⏳ Đang chạy: total_md_split.py...", None
    split_cmd = ["python3", "skills/ppt-master/scripts/total_md_split.py", project_path]
    subprocess.run(split_cmd, cwd=PROJECT_ROOT)
    
    yield "⏳ Đang chạy: finalize_svg.py...", None
    finalize_cmd = ["python3", "skills/ppt-master/scripts/finalize_svg.py", project_path]
    subprocess.run(finalize_cmd, cwd=PROJECT_ROOT)
    
    yield "⏳ Đang chạy: svg_to_pptx.py (Export)...", None
    export_cmd = ["python3", "skills/ppt-master/scripts/svg_to_pptx.py", project_path, "-s", "final"]
    export_result = subprocess.run(export_cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    
    if export_result.returncode != 0:
        yield f"❌ Lỗi khi xuất PPTX:\n{export_result.stderr}", None
        return
        
    # Tìm file PPTX được xuất ra
    exports_dir = os.path.join(project_path, "exports")
    pptx_files = [f for f in os.listdir(exports_dir) if f.endswith(".pptx") and not f.endswith("_svg.pptx")]
    
    if not pptx_files:
        yield "❌ Không tìm thấy file PPTX sau khi xuất.", None
        return
        
    final_pptx_path = os.path.join(exports_dir, pptx_files[0])
    
    yield "🎉 Hoàn thành! File PPTX đã sẵn sàng để tải xuống.", final_pptx_path

# --- UI Definition ---
with gr.Blocks(title="PPT Master - Web Demo", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🎨 PPT Master - AI Presentation Generator")
    gr.Markdown("Đây là bản demo giao diện web (Gradio) giả lập quy trình của PPT Master. Chức năng gọi API LLM thực tế được mock bằng các slide mặc định để bạn có thể kiểm thử toàn bộ luồng post-processing (SVG to PPTX) của hệ thống.")
    
    with gr.Row():
        with gr.Column(scale=2):
            topic_input = gr.Textbox(label="Nhập chủ đề trình bày", placeholder="Ví dụ: Chiến lược Marketing 2026...", lines=2)
            file_input = gr.File(label="Tải lên tài liệu hoặc hình ảnh (PDF, DOCX, PNG, JPG...)", file_count="multiple")
            num_slides = gr.Slider(minimum=1, maximum=10, value=3, step=1, label="Số lượng Slide")
            
            # Khung nhập API Key
            api_key = gr.Textbox(label="OpenAI / Gemini API Key", placeholder="Nhập sk-... hoặc AIza...", type="password")
            
            generate_btn = gr.Button("🚀 Tạo Presentation", variant="primary")
            
        with gr.Column(scale=3):
            status_output = gr.Textbox(label="Trạng thái hệ thống", lines=10, interactive=False)
            file_output = gr.File(label="Tải xuống File PPTX")
            
    generate_btn.click(
        fn=generate_ppt,
        inputs=[topic_input, file_input, num_slides, api_key],
        outputs=[status_output, file_output]
    )

if __name__ == "__main__":
    demo.launch(share=True)
