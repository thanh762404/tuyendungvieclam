import re


SKILLS_BY_MAJOR = {
    'Công nghệ thông tin': (
        'Python', 'Java', 'ReactJS', 'MySQL', 'Django', 'HTML/CSS', 'Node.js', 'Tester',
    ),
    'Quản trị kinh doanh': (
        'Quản lý dự án', 'Quản lý nhân sự', 'Phân tích kinh doanh', 'Microsoft Excel',
    ),
    'Thiết kế đồ họa': ('Photoshop', 'UI/UX Design', 'Figma'),
    'Logistics': (
        'Quản lý kho', 'Quản lý chuỗi cung ứng', 'Xuất nhập khẩu', 'Microsoft Excel',
    ),
    'Ngôn ngữ Anh': ('English', 'Translation', 'IELTS', 'TOEIC'),
    'Tài chính – Ngân hàng': (
        'Nghiệp vụ ngân hàng', 'Tín dụng ngân hàng', 'Kế toán ngân hàng', 'Chăm sóc khách hàng',
    ),
}


def invalid_skills_for_major(major, skills_text):
    allowed = {skill.casefold() for skill in SKILLS_BY_MAJOR.get(major, ())}
    selected = [
        skill.strip()
        for skill in re.split(r'[,;\n]+', skills_text or '')
        if skill.strip()
    ]
    return [skill for skill in selected if skill.casefold() not in allowed]