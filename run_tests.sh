#!/bin/bash

# PYTHONPATH 설정은 그대로 두지만, python -m pytest를 시도해봅니다.
# python -m은 현재 디렉토리를 PYTHONPATH에 추가하는 효과가 있습니다.
export PYTHONPATH=$(pwd) # 이 라인은 유지해도 무방합니다.

# python 모듈로 pytest 실행
python -m pytest "$@"