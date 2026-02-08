"""
Health Label DXF Generator - Streamlit Web App
Generates DXF files with MTEXT, polylines and QR codes
Requirements: pip install streamlit ezdxf pillow numpy
Run with: streamlit run streamlit_app.py
"""
import streamlit as st
import ezdxf
from ezdxf import units
import os
import tempfile
import zipfile
import re
from io import BytesIO
from PIL import Image
import numpy as np

# Page configuration
st.set_page_config(
    page_title="Health Label DXF Generator",
    page_icon="🏷️",
    layout="wide"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 10px;
        margin-bottom: 2rem;
        color: white;
        text-align: center;
    }
    .main-header h1 {
        margin: 0;
        font-size: 2.5rem;
    }
    .main-header p {
        margin: 0.5rem 0 0 0;
        opacity: 0.9;
    }
    .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        padding: 0.75rem 2rem;
        font-size: 1.1rem;
        border-radius: 8px;
        width: 100%;
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #764ba2 0%, #667eea 100%);
    }
    .info-card {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #667eea;
        margin: 1rem 0;
    }
    .success-box {
        background: #d4edda;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #28a745;
    }
</style>
""", unsafe_allow_html=True)

DEFAULT_CONFIG = {
    "canvas_width_mm": 600, "canvas_height_mm": 300,
    "label_width_mm": 65, "label_height_mm": 20,
    "org_name": "HEALTH", "subtitle1": "South Eastern Sydney", "subtitle2": "Local Health District",
    "footer_text": "DO NOT REMOVE ASSET - CONTACT TAM",
    "text_color": 5, "cutting_color": 1, "break_color": 4, "line_width": 0.3,
    "qr_size_mm": 11.5, "qr_x_offset": 49, "qr_y_offset": 3,
}

class HealthLabelGenerator:
    def __init__(self, config=None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
    
    def create_dxf(self, labels, output_path, qr_images=None):
        """Create DXF file with labels and optional QR codes."""
        doc = ezdxf.new('R2013', units=units.MM)
        doc.header['$MEASUREMENT'], doc.header['$INSUNITS'] = 1, 4
        for name, color in [('Cutting', 'cutting_color'), ('Break', 'break_color'), 
                            ('TEXT', 'text_color'), ('QR', 'text_color')]:
            doc.layers.add(name, color=self.config[color])
        doc.styles.add('CALIBRI', font='calibri.ttf')
        msp = doc.modelspace()
        
        cfg = self.config
        label_w, label_h = cfg['label_width_mm'], cfg['label_height_mm']
        cols = int(cfg['canvas_width_mm'] // label_w)
        rows_max = int(cfg['canvas_height_mm'] // label_h)
        used_cols = min(cols, len(labels))
        used_rows = (len(labels) + cols - 1) // cols
        grid_h = used_rows * label_h
        
        for idx, name in enumerate(labels[:cols * rows_max]):
            col, row = idx % cols, idx // cols
            x, y = col * label_w, row * label_h
            dxf_x, dxf_y = x, grid_h - y - label_h
            
            edges = [(col == 0, 'left'), (col == used_cols - 1, 'right'),
                     (row == 0, 'top'), (row == used_rows - 1, 'bottom')]
            lines = [((dxf_x, dxf_y), (dxf_x + label_w, dxf_y), edges[3][0]),
                     ((dxf_x + label_w, dxf_y), (dxf_x + label_w, dxf_y + label_h), edges[1][0]),
                     ((dxf_x + label_w, dxf_y + label_h), (dxf_x, dxf_y + label_h), edges[2][0]),
                     ((dxf_x, dxf_y + label_h), (dxf_x, dxf_y), edges[0][0])]
            for p1, p2, is_outer in lines:
                msp.add_line(p1, p2, dxfattribs={'layer': 'Cutting' if is_outer else 'Break'})
            
            self._draw_label(msp, x, y, name, grid_h, qr_images)
        
        doc.saveas(output_path)
        return output_path
    
    def _draw_label(self, msp, x, y, label_name, grid_h, qr_images=None):
        flipY = lambda sy: grid_h - sy
        cfg = self.config
        
        texts = [
            (cfg['org_name'], x + 13, y + 4.7, 2),
            (cfg['subtitle1'], x + 13, y + 7.2, 1.3),
            (cfg['subtitle2'], x + 13, y + 9.2, 1.3),
            (label_name, x + 7, y + 15.7, 2),
            (cfg['footer_text'], x + 19, y + 18, 1),
        ]
        for text, tx, ty, h in texts:
            mt = msp.add_mtext(text)
            mt.dxf.layer, mt.dxf.insert, mt.dxf.char_height = 'TEXT', (tx, flipY(ty)), h
            mt.dxf.attachment_point, mt.dxf.style = 7, 'CALIBRI'
        
        msp.add_lwpolyline([(x + 12.2, flipY(y + 2.2)), (x + 12.2, flipY(y + 10.2))],
                           dxfattribs={'layer': 'TEXT', 'const_width': cfg['line_width']})
        
        if qr_images and label_name in qr_images:
            qr_y = flipY(y + cfg['qr_y_offset'] + cfg['qr_size_mm'])
            self._draw_qr_from_image(msp, qr_images[label_name], x + cfg['qr_x_offset'], qr_y, cfg['qr_size_mm'])
    
    def _draw_qr_from_image(self, msp, img_data, dxf_x, dxf_y, size_mm):
        """Draw QR code from image data (PIL Image or bytes)."""
        if isinstance(img_data, bytes):
            img = Image.open(BytesIO(img_data)).convert('L')
        else:
            img = img_data.convert('L')
        
        img_array = np.array(img) < 128
        rows, cols = np.any(img_array, 1), np.any(img_array, 0)
        if not rows.any(): 
            return
        r0, r1 = np.where(rows)[0][[0, -1]]
        c0, c1 = np.where(cols)[0][[0, -1]]
        qr = img_array[r0:r1+1, c0:c1+1]
        h, w = qr.shape
        
        # Robust module size estimation
        run_lengths = []
        for row_idx in range(0, h, max(1, h // 10)):
            row = qr[row_idx, :]
            trans = np.where(np.diff(row.astype(int)) != 0)[0]
            if len(trans) > 1:
                run_lengths.extend(np.diff(trans).tolist())
        for col_idx in range(0, w, max(1, w // 10)):
            col = qr[:, col_idx]
            trans = np.where(np.diff(col.astype(int)) != 0)[0]
            if len(trans) > 1:
                run_lengths.extend(np.diff(trans).tolist())
        
        if run_lengths:
            run_lengths = np.array(run_lengths)
            median_run = np.median(run_lengths)
            filtered = run_lengths[(run_lengths >= median_run * 0.5) & (run_lengths <= median_run * 1.5)]
            px = int(round(np.median(filtered))) if len(filtered) > 0 else int(round(median_run))
        else:
            px = max(1, min(h, w) // 21)
        
        px = max(1, px)
        n = max(int(round(w / px)), int(round(h / px)))
        n = max(21, min(n, 177))
        mm = size_mm / n
        
        for r in range(n):
            for c in range(n):
                ix, iy = min(int((c + 0.5) * w / n), w - 1), min(int((r + 0.5) * h / n), h - 1)
                if qr[iy, ix]:
                    mx, my = dxf_x + c * mm, dxf_y + (n - 1 - r) * mm
                    hatch = msp.add_hatch(color=self.config['text_color'], dxfattribs={'layer': 'QR'})
                    hatch.paths.add_polyline_path([(mx, my), (mx + mm, my), 
                                                   (mx + mm, my + mm), (mx, my + mm)], is_closed=True)
    
    def create_multi_page_dxf(self, labels, output_dir, base_name="MLA Black On White 0.8mm 01", qr_images=None):
        """Create multi-page DXF files if labels exceed single page capacity."""
        os.makedirs(output_dir, exist_ok=True)
        cfg = self.config
        cols = int(cfg['canvas_width_mm'] // cfg['label_width_mm'])
        per_page = cols * int(cfg['canvas_height_mm'] // cfg['label_height_mm'])
        pages = (len(labels) + per_page - 1) // per_page
        
        files = []
        for p in range(pages):
            page_labels = labels[p * per_page:(p + 1) * per_page]
            fname = f"{base_name}.dxf" if pages == 1 else f"{base_name[:-2]}{p + 1:02d}.dxf"
            self.create_dxf(page_labels, os.path.join(output_dir, fname), qr_images)
            files.append(fname)
        return files


def parse_uploaded_files(uploaded_files):
    """Parse uploaded QR code files and extract labels with quantity support."""
    labels = []
    qr_images = {}
    
    for uploaded_file in sorted(uploaded_files, key=lambda x: x.name):
        name = os.path.splitext(uploaded_file.name)[0]
        uploaded_file.seek(0)  # Reset file pointer before reading
        img_data = uploaded_file.read()
        
        # Check for _x# suffix for quantity (e.g., SGH.KSB.B1.03001_x4)
        match = re.match(r'^(.+)_x(\d+)$', name)
        if match:
            base_name, qty = match.group(1), int(match.group(2))
            labels.extend([base_name] * qty)
            qr_images[base_name] = img_data
        else:
            labels.append(name)
            qr_images[name] = img_data
    
    return labels, qr_images


def main():
    # Header
    st.markdown("""
    <div class="main-header">
        <h1>🏷️ Health Label DXF Generator</h1>
        <p>Generate DXF label files with QR codes</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar for configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        st.subheader("📐 Canvas Settings")
        canvas_width = st.number_input("Canvas Width (mm)", value=600.0, min_value=100.0, step=10.0)
        canvas_height = st.number_input("Canvas Height (mm)", value=300.0, min_value=100.0, step=10.0)
        
        st.subheader("🏷️ Label Settings")
        label_width = st.number_input("Label Width (mm)", value=65.0, min_value=20.0, step=1.0)
        label_height = st.number_input("Label Height (mm)", value=20.0, min_value=10.0, step=1.0)
        
        st.subheader("📱 QR Code Settings")
        qr_size = st.number_input("QR Size (mm)", value=11.5, min_value=5.0, step=0.5)
        qr_x_offset = st.number_input("QR X Offset (mm)", value=49.0, step=1.0)
        qr_y_offset = st.number_input("QR Y Offset (mm)", value=3.0, step=0.5)
        
        st.subheader("📝 Label Text")
        org_name = st.text_input("Organization Name", value="HEALTH")
        subtitle1 = st.text_input("Subtitle 1", value="South Eastern Sydney")
        subtitle2 = st.text_input("Subtitle 2", value="Local Health District")
        footer_text = st.text_input("Footer Text", value="DO NOT REMOVE ASSET - CONTACT TAM")
        
        include_qr = st.checkbox("Include QR Codes", value=True)
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("📤 Upload QR Code Images")
        st.markdown("""
        <div class="info-card">
            <strong>Instructions:</strong><br>
            • Upload PNG files named with the label identifier (e.g., <code>SGH.KSB.B1.03001.png</code>)<br>
            • For duplicates, add <code>_x#</code> suffix (e.g., <code>SGH.KSB.B1.03001_x4.png</code> creates 4 copies)<br>
            • The filename (without extension) becomes the label name
        </div>
        """, unsafe_allow_html=True)
        
        uploaded_files = st.file_uploader(
            "Choose QR code PNG files",
            type=['png'],
            accept_multiple_files=True
        )
    
    with col2:
        st.subheader("📊 Summary")
        if uploaded_files:
            labels, qr_images = parse_uploaded_files(uploaded_files)
            
            config = {
                "canvas_width_mm": canvas_width,
                "canvas_height_mm": canvas_height,
                "label_width_mm": label_width,
                "label_height_mm": label_height,
                "qr_size_mm": qr_size,
                "qr_x_offset": qr_x_offset,
                "qr_y_offset": qr_y_offset,
                "org_name": org_name,
                "subtitle1": subtitle1,
                "subtitle2": subtitle2,
                "footer_text": footer_text,
            }
            
            cols_per_page = int(canvas_width // label_width)
            rows_per_page = int(canvas_height // label_height)
            labels_per_page = cols_per_page * rows_per_page
            num_pages = (len(labels) + labels_per_page - 1) // labels_per_page
            
            st.metric("QR Files Uploaded", len(uploaded_files))
            st.metric("Total Labels", len(labels))
            st.metric("Labels per Page", labels_per_page)
            st.metric("DXF Pages", num_pages)
        else:
            st.info("Upload QR code files to see summary")
    
    # Generate button
    st.markdown("---")
    
    if uploaded_files:
        if st.button("🚀 Generate DXF Files", use_container_width=True):
            with st.spinner("Generating DXF files..."):
                labels, qr_images = parse_uploaded_files(uploaded_files)
                
                config = {
                    "canvas_width_mm": canvas_width,
                    "canvas_height_mm": canvas_height,
                    "label_width_mm": label_width,
                    "label_height_mm": label_height,
                    "qr_size_mm": qr_size,
                    "qr_x_offset": qr_x_offset,
                    "qr_y_offset": qr_y_offset,
                    "org_name": org_name,
                    "subtitle1": subtitle1,
                    "subtitle2": subtitle2,
                    "footer_text": footer_text,
                }
                
                generator = HealthLabelGenerator(config)
                
                with tempfile.TemporaryDirectory() as temp_dir:
                    files = generator.create_multi_page_dxf(
                        labels, 
                        temp_dir, 
                        qr_images=qr_images if include_qr else None
                    )
                    
                    # Create ZIP file for download
                    zip_buffer = BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                        for fname in files:
                            file_path = os.path.join(temp_dir, fname)
                            zip_file.write(file_path, fname)
                    
                    zip_buffer.seek(0)
                    
                    st.markdown("""
                    <div class="success-box">
                        ✅ <strong>DXF files generated successfully!</strong>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    st.download_button(
                        label="📥 Download DXF Files (ZIP)",
                        data=zip_buffer.getvalue(),
                        file_name="health_labels.zip",
                        mime="application/zip",
                        use_container_width=True
                    )
                    
                    # Show generated files
                    st.subheader("📁 Generated Files")
                    for fname in files:
                        st.text(f"• {fname}")
    else:
        st.warning("👆 Please upload QR code PNG files to generate DXF labels")
    
    # Preview section
    if uploaded_files:
        st.markdown("---")
        with st.expander("👁️ Preview Uploaded QR Codes"):
            preview_cols = st.columns(6)
            for idx, uploaded_file in enumerate(uploaded_files[:12]):
                uploaded_file.seek(0)
                with preview_cols[idx % 6]:
                    st.image(uploaded_file, caption=uploaded_file.name, width=100)


if __name__ == "__main__":
    main()
