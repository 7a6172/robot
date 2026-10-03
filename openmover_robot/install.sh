# sudo
read -s -n1 -p "准备配置权限并进行准备，按任意键继续..."
echo
USER="$(id -un)"
FILE="/etc/sudoers.d/${USER}-nopasswd"
LINE="${USER} ALL=(ALL) NOPASSWD:ALL"
sudo -v
if ! (sudo test -f "$FILE" && sudo grep -Fxq "$LINE" "$FILE"); then
  echo "$LINE" | sudo tee "$FILE" >/dev/null
  sudo chmod 0440 "$FILE"
fi
sudo apt update
sudo apt upgrade -y
sudo apt autoremove -y

# 更新内核
read -s -n1 -p "准备更新内核，按任意键继续..."
echo
sudo add-apt-repository ppa:tuxinvader/lts-mainline-longterm
sudo apt update
sudo apt install linux-generic-6.01

# ROS本体
read -s -n1 -p "准备安装 ROS Noetic，按任意键继续..."
echo
sudo sh -c '. /etc/lsb-release && echo "deb http://mirrors.ustc.edu.cn/ros/ubuntu/ `lsb_release -cs` main" > /etc/apt/sources.list.d/ros-latest.list'
sudo apt install -y curl
sudo apt-key add ~/openmover_robot/ros.asc
sudo apt update
sudo apt install -y ros-noetic-desktop-full
sudo apt-get install -y ros-noetic-joint-state-controller ros-noetic-position-controllers ros-noetic-navigation ros-noetic-slam-gmapping ros-noetic-robot-pose-ekf ros-noetic-teb-local-planner ros-noetic-joy ros-noetic-octomap* ros-noetic-tf2* ignition* libignition-math* libmodbus* openssh-server
sudo ufw allow ssh
source /opt/ros/noetic/setup.bash
echo "source /opt/ros/noetic/setup.bash" >> ~/.bashrc
sudo apt install -y python3-rosdep python3-rosinstall python3-rosinstall-generator python3-wstool build-essential

# ROS
read -s -n1 -p "准备安装 ROS Noetic 附加组件，按任意键继续..."
echo
sudo apt-get install -y ros-noetic-joint-state-controller ros-noetic-position-controllers ros-noetic-navigation ros-noetic-slam-gmapping ros-noetic-robot-pose-ekf ros-noetic-teb-local-planner ros-noetic-joy ros-noetic-octomap* libudev* ros-noetic-serial* ros-noetic-rosbridge-server libpcap* ros-noetic-tf2* libmodbus*
source /opt/ros/noetic/setup.bash
sudo apt install -y python3-rosdep python3-rosinstall python3-rosinstall-generator python3-wstool build-essential

# Cartographer
read -s -n1 -p "准备安装 Cartographer，按任意键继续..."
echo
sudo apt-get install -y ninja-build stow
sudo apt-get install -y clang cmake g++ git google-mock libboost-all-dev libboost-iostreams-dev libcairo2-dev libceres-dev libcurl4-openssl-dev libeigen3-dev libgflags-dev libgoogle-glog-dev liblua5.2-dev libsuitesparse-dev lsb-release ninja-build python3-sphinx stow
sudo apt-get install -y libgmock-dev protobuf-compiler libprotobuf-dev
cd ~/openmover_robot/cartographer_ws/abseil-cpp
sudo rm -rf build
mkdir build
cd build
cmake -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DCMAKE_INSTALL_PREFIX=/usr/local/stow/absl ..
ninja
sudo ninja install
cd /usr/local/stow
sudo stow absl
cd ~/openmover_robot/cartographer_ws
sudo rm -rf build_isolated
sudo rm -rf devel_isolated
sudo rm -rf install_isolated
source /opt/ros/noetic/setup.bash
catkin_make_isolated --install --use-ninja
echo "source ~/openmover_robot/cartographer_ws/install_isolated/setup.bash --extend" >> ~/.bashrc
source ~/openmover_robot/cartographer_ws/install_isolated/setup.bash

# osqp
read -s -n1 -p "准备安装 osqp，按任意键继续..."
echo
cd ~/openmover_robot/osqp
sudo rm -rf build
mkdir build
cd build
cmake -G "Unix Makefiles" ..
cmake --build .
sudo cmake --build . --target install

# openmover
read -s -n1 -p "准备安装 openmover，按任意键继续..."
echo
cd ~/openmover_robot/openmover_ws
sudo rm -rf build
sudo rm -rf devel
sudo rm -rf install
catkin_make -DCATKIN_WHITELIST_PACKAGES=warehouse_simulation
catkin_make -DCATKIN_WHITELIST_PACKAGES=ira_laser_tools
catkin_make -DCATKIN_WHITELIST_PACKAGES=relocalization_toolbox_msgs
catkin_make -DCATKIN_WHITELIST_PACKAGES=relocalization_toolbox
catkin_make -DCATKIN_WHITELIST_PACKAGES=openmover_msgs
source ~/openmover_robot/openmover_ws/devel/setup.bash
catkin_make -DCATKIN_WHITELIST_PACKAGES=auto_mapping_toolbox_msgs
catkin_make -DCATKIN_WHITELIST_PACKAGES=auto_mapping_toolbox
echo "source ~/openmover_robot/openmover_ws/devel/setup.bash --extend" >> ~/.bashrc
source ~/openmover_robot/openmover_ws/devel/setup.bash
catkin_make -DCATKIN_WHITELIST_PACKAGES=bluesea2
source ~/openmover_robot/openmover_ws/devel/setup.bash
catkin_make -DCATKIN_WHITELIST_PACKAGES=openmover
echo 'export PYTHONPATH=$PYTHONPATH:~/openmover_robot/openmover_ws/src/openmover/scripts/hal' >> ~/.bashrc
source ~/.bashrc
echo "export DISABLE_ROS1_EOL_WARNINGS=1" >> ~/.bashrc

# Python PIP
read -s -n1 -p "准备安装 Python 依赖，按任意键继续..."
echo
sudo apt install -y python3-pip
pip3 config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple/
pip3 install pygame
pip3 install pynput

# Apply Changes
source ~/openmover_robot/cartographer_ws/install_isolated/setup.bash
source ~/openmover_robot/openmover_ws/devel/setup.bash
