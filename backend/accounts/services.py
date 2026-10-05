import logging
import os
import re


logger = logging.getLogger(__name__)

CV_SKILL_KEYWORDS = (
    'python', 'django', 'tester', 'node.js', 'nodejs', 'reactjs', 'mysql', 'sql', 'java', 'c#', 'php',
    'data engineering', 'data analysis', 'data analyst', 'business intelligence',
    'pandas', 'numpy', 'postgresql', 'power bi', 'microsoft excel', 'excel', 'ui/ux design', 'ui/ux', 'figma',
    'photoshop', 'illustrator', 'marketing', 'sales', 'seo', 'social media',
    'google ads', 'facebook ads', 'kế toán', 'accounting', 'finance', 'banking',
    'customer service', 'chăm sóc khách hàng', 'tiếng anh', 'english', 'translation',
    'ielts', 'toeic', 'hotel', 'tourism', 'devops', 'quản lý dự án', 'quản lý nhân sự',
    'phân tích kinh doanh', 'quản lý kho', 'quản lý chuỗi cung ứng', 'xuất nhập khẩu',
    'nghiệp vụ ngân hàng', 'tín dụng ngân hàng', 'kế toán ngân hàng',
    'javascript', 'html/css', 'html5', 'css3', 'flask', 'angular', 'vuejs', 'fullstack',
)


def extract_skills_from_file(file_field):
    """Read common skills from a PDF or Word CV."""
    if not file_field:
        return []

    file_extension = os.path.splitext(file_field.name)[1].lower()
    text = ''
    try:
        if file_extension == '.pdf':
            from pypdf import PdfReader

            reader = PdfReader(file_field)
            for page in reader.pages:
                text += (page.extract_text() or '') + '\n'
        elif file_extension == '.docx':
            from docx import Document

            document = Document(file_field)
            text = '\n'.join(paragraph.text for paragraph in document.paragraphs)
    except Exception as error:
        logger.warning('Could not extract skills from uploaded CV (%s).', type(error).__name__)
        return []

    text = text.casefold()
    return [
        skill for skill in CV_SKILL_KEYWORDS
        if re.search(rf'(?<!\w){re.escape(skill)}(?!\w)', text)
    ]