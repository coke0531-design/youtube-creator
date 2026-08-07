import {Config} from '@remotion/cli/config';

// capture_slides.py와 동일한 산출 조건에 맞춤: jpeg 프레임 → h264, 덮어쓰기 허용
Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
