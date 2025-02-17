﻿# -*- coding: utf-8 -*-

from cv2_VideoCapture import initialize_camera, get_frame
import cv2
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from torchvision import transforms
import time


device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

class TicTacToeCNN(nn.Module):
    def __init__(self):
        super(TicTacToeCNN, self).__init__()
        self.conv1 = nn.Conv2d(3, 64, kernel_size=3, stride=1, padding=1)
        self.conv2 = nn.Conv2d(64, 128, kernel_size=3, stride=1, padding=1)
        self.conv3 = nn.Conv2d(128, 256, kernel_size=3, stride=1, padding=1)
        self.bn1 = nn.BatchNorm2d(64)
        self.bn2 = nn.BatchNorm2d(128)
        self.bn3 = nn.BatchNorm2d(256)
        self.dropout = nn.Dropout(0.2)
        self.fc1 = nn.Linear(256*4*4, 128)
        self.fc2 = nn.Linear(128, 9*3)  # O, X, blank (3 classes)

    def forward(self, x):
        x = F.relu(self.bn1(self.conv1(x)))
        x = F.max_pool2d(x, 2)
        x = F.relu(self.bn2(self.conv2(x)))
        x = F.max_pool2d(x, 2)
        x = F.relu(self.bn3(self.conv3(x)))
        x = F.max_pool2d(x, 2)
        x = x.view(x.size(0), -1)  # Flatten
        x = F.relu(self.fc1(x))
        x = self.dropout(x)
        x = self.fc2(x)

        x = x.view(x.size(0), 9, 3)
        return x

transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Resize((32, 32)),
])

def preprocess_image(frame):
    input_tensor = transform(frame).unsqueeze(0).to(device)
    return input_tensor

def classify_cell(model, frame):
    input_tensor = preprocess_image(frame)
    with torch.no_grad():
        output = model(input_tensor)
    board_state = torch.argmax(output, dim=2).cpu().numpy()
    return board_state

def extract_square_board(frame):
    """
    카메라 각도 때문에 비정형 사각형으로 인식되는 틱택토 보드를 
    정사각형으로 보정하여 인식
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # 그림자 보정 옵션들
    """
    # 1. 특정 임계값 이하의 픽셀을 흰색으로 설정
    shadow_threshold = 100 # 그림자를 제거하기 위한 임계값
    gray[gray < shadow_threshold] = 255 # 임계값 이하를 흰색으로 설정
    _, thresh = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    """

    """
    # 2. adaptiveThreshold: 이미지의 지역적 특성에 따라 임계값 다르게 적용
    # 조명이 불균형하거나 다양한 조명 조건이 있는 이미지에서 유용
    # 그림자 문제 해결? -> 테스트 해봐야함
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    edges = cv2.Canny(thresh, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    """


    # 흑백 반전된 이미지가 들어온다는 것을 고려!!
    # 3. 임계값 지정 + 얇은 선 잘 인식 
    # shadow_threshold = 100  # 그림자를 제거하기 위한 임계값
    # gray[gray < shadow_threshold] = 255  # 임계값 이하를 검은색으로 설정
    # equalized_gray = cv2.equalizeHist(gray)

    # blurred = cv2.GaussianBlur(equalized_gray, (5, 5), 0)
    edges = cv2.Canny(gray, 50, 150)
    dilated = cv2.dilate(edges, None, iterations=5)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # 이미지 크기 계산
    frame_height, frame_width = frame.shape[:2]
    frame_area = frame_height * frame_width

    if contours:
        largest_contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest_contour)

        # 이미지의 꼭짓점을 찾는 것을 방지하기 위해
        # 이미지 크기 내부에서 보드를 찾도록 범위 지정
        if frame_area * 0.01 < area < frame_area * 0.9:
            epsilon = 0.02 * cv2.arcLength(largest_contour, True)
            approx = cv2.approxPolyDP(largest_contour, epsilon, True)

            if len(approx) == 4:
                points = np.array([point[0] for point in approx])
                sorted_points = order_points(points)

                # 디버깅 (찾은 꼭짓점 시각화)
                for corner in sorted_points:
                    x, y = corner
                    cv2.circle(frame, (int(x), int(y)), 10, (0, 0, 255), -1)

                square_size = 300
                dst_points = np.array([
                    [0, 0],
                    [square_size - 1, 0],
                    [square_size - 1, square_size - 1],
                    [0, square_size - 1]
                    ], dtype="float32")

                # 투시 변환 행렬 계산
                matrix = cv2.getPerspectiveTransform(sorted_points, dst_points)
                board_img = cv2.warpPerspective(frame, matrix, (square_size, square_size))
        
                _, board_img_thresh = cv2.threshold(cv2.cvtColor(board_img, cv2.COLOR_BGR2GRAY), 
                                                128, 255, cv2.THRESH_BINARY)
                board_img_colored = cv2.cvtColor(board_img_thresh, cv2.COLOR_GRAY2BGR)

                cv2.drawContours(frame, [largest_contour], -1, (0, 255, 0), 3)

                return board_img_colored
        
            else:
                print("Falied to find 4 corners.")
        else: 
            print(f"Contour area out of range: {area}")
    else:
        print("No contours found.")

    return None

def order_points(points):
    """ 
    좌표 정렬: 좌상, 우상, 우하, 좌하 순서
    """
    rect = np.zeros((4, 2), dtype="float32")
    s = points.sum(axis=1)
    rect[0] = points[np.argmin(s)] # 좌상
    rect[2] = points[np.argmax(s)] # 우하

    diff = np.diff(points, axis=1)
    rect[1] = points[np.argmin(diff)] # 우상
    rect[3] = points[np.argmax(diff)] # 좌하

    return rect

def classify_board(board_img, model):
    board_img_resized = cv2.resize(board_img, (96, 96))
    board_state = classify_cell(model, board_img_resized)
    return board_state

def camera_to_state(state):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    model = TicTacToeCNN().to(device)
    model.load_state_dict(torch.load(r"C:\Temp\model_state_dict.pt", map_location=torch.device('cpu'), weights_only=True))
    model.eval()

    prev_pred = None # 이전 상태
    stable_pred = None # 안정화된 보드 상태 저장
    last_change_time = time.time() # 마지막으로 변화가 감지된 시간
    stability_duration = 2 # 안정화 시간 기준 (초)

    vcap = initialize_camera(1)
    if not vcap.isOpened():
        raise IOError('camera is not opened!')

    while True:
        frame = get_frame(vcap)
        if frame is None:
            break

        # 흑백 전환
        frame = cv2.bitwise_not(frame)

        board_img = extract_square_board(frame)
        if board_img is None:
            # print("No board detected. Try again...")
            continue

        board_state = classify_board(board_img, model)
        if board_state is None:
            continue

        pred = np.array(board_state) # numpy 배열로 변환

        # 보드 상태 변화 감지
        if prev_pred is None or not np.array_equal(pred, prev_pred):
            last_change_time = time.time()

        # 안정화 조건 확인
        if time.time() - last_change_time > stability_duration:
            if stable_pred is None or not np.array_equal(pred, stable_pred):  # 배열 비교
                stable_pred = pred
                print("Stable Board State Detected (O=0, X=1, Blank=2):")
                print(stable_pred)
                
            # 상태 반환
            if stable_pred is not None and not np.array_equal(state, stable_pred):
                # 디버깅
                print("Initial state:")
                print(state)
                print("Stable prediction:")
                print(stable_pred)
                return stable_pred # 최종 변화 상태 반환

        prev_pred = pred

        cv2.imshow("Tic-Tac-Toe Board Detection", frame)

        if cv2.waitKey(10) == 27:
            break

    vcap.release()
    cv2.destroyAllWindows()