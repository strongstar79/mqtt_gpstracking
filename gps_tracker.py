import re
import ast
import os
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from werkzeug.utils import secure_filename
from math import radians, cos, sin, asin, sqrt

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size

# 업로드 폴더 생성
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('static', exist_ok=True)

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    두 지점 간의 거리를 미터 단위로 계산 (Haversine 공식)
    """
    R = 6371000  # 지구 반지름 (미터)
    
    lat1_rad = radians(lat1)
    lat2_rad = radians(lat2)
    delta_lat = radians(lat2 - lat1)
    delta_lon = radians(lon2 - lon1)
    
    a = sin(delta_lat/2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon/2)**2
    c = 2 * asin(sqrt(a))
    
    return R * c

def parse_log_file(filename):
    """
    로그 파일을 파싱하여 GPS 좌표 데이터 추출
    """
    gps_data = []
    
    with open(filename, 'r', encoding='utf-8') as f:
        for line in f:
            # 딕셔너리 부분 추출
            match = re.search(r"\{'TIMESTAMP':.*?\}", line)
            if match:
                try:
                    # 문자열을 딕셔너리로 변환
                    data_str = match.group(0).replace("'", '"')
                    data = ast.literal_eval(match.group(0))
                    
                    # 타임스탬프 추출
                    timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                    if timestamp_match:
                        timestamp = timestamp_match.group(1)
                        
                        lat = float(data.get('LAT', 0))
                        lon = float(data.get('LON', 0))
                        
                        # 0,0 좌표 제외
                        if lat != 0.0 or lon != 0.0:
                            gps_data.append({
                                'timestamp': timestamp,
                                'lat': lat,
                                'lon': lon,
                                'alt': float(data.get('ALT', 0)),
                                'kph': data.get('KPH', '0.0'),
                                'qual': int(data.get('QUAL', 0)),
                                'equip_type': data.get('EQUIP_TYPE', ''),
                                'equip_id': data.get('EQUIP_ID', '')
                            })
                except:
                    continue
    
    # 시간순으로 정렬
    gps_data.sort(key=lambda x: x['timestamp'])
    
    return gps_data

def filter_by_distance(gps_data, min_distance=5.0):
    """
    직전 플롯한 지점과 최소 거리(미터) 이상 떨어진 점만 필터링
    """
    if not gps_data:
        return []
    
    filtered_data = [gps_data[0]]  # 첫 번째 점은 항상 포함
    
    for point in gps_data[1:]:
        last_point = filtered_data[-1]
        distance = haversine_distance(
            last_point['lat'], last_point['lon'],
            point['lat'], point['lon']
        )
        
        if distance >= min_distance:
            filtered_data.append(point)
    
    return filtered_data

@app.route('/')
def index():
    """메인 페이지"""
    return render_template('index.html')

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """로그 파일 업로드"""
    if 'file' not in request.files:
        return jsonify({'error': '파일이 없습니다.'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '파일이 선택되지 않았습니다.'}), 400
    
    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        return jsonify({'filename': filename, 'message': '파일이 업로드되었습니다.'})

@app.route('/api/track')
def get_track():
    """GPS 트래킹 데이터 API"""
    filename = request.args.get('filename', 'mqtt_messages_2025-12-11_153030_1_short.log')
    
    # 업로드된 파일이 있으면 그것을 사용, 없으면 기본 파일 사용
    if filename.startswith('uploads/'):
        log_file = filename
    elif os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], filename)):
        log_file = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    else:
        # 기본 파일이 현재 디렉토리에 있는지 확인
        if os.path.exists(filename):
            log_file = filename
        else:
            return jsonify({'error': '파일을 찾을 수 없습니다.'}), 404
    
    # 로그 파일 파싱
    gps_data = parse_log_file(log_file)
    
    if not gps_data:
        return jsonify({'error': 'GPS 데이터를 찾을 수 없습니다.'}), 404
    
    # EQUIP_TYPE과 EQUIP_ID 추출 (첫 번째 유효한 데이터에서)
    equip_type = gps_data[0].get('equip_type', '') if gps_data else ''
    equip_id = gps_data[0].get('equip_id', '') if gps_data else ''
    
    # 5미터 이상 떨어진 점만 필터링
    filtered_data = filter_by_distance(gps_data, min_distance=5.0)
    
    return jsonify({
        'points': filtered_data,
        'total_points': len(filtered_data),
        'original_points': len(gps_data),
        'equip_type': equip_type,
        'equip_id': equip_id
    })

@app.route('/api/files')
def list_files():
    """사용 가능한 로그 파일 목록"""
    files = []
    # 현재 디렉토리의 .log 파일
    for f in os.listdir('.'):
        if f.endswith('.log'):
            files.append({'name': f, 'path': f})
    # 업로드 폴더의 파일
    if os.path.exists(app.config['UPLOAD_FOLDER']):
        for f in os.listdir(app.config['UPLOAD_FOLDER']):
            if f.endswith('.log'):
                files.append({'name': f, 'path': os.path.join('uploads', f)})
    return jsonify({'files': files})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

