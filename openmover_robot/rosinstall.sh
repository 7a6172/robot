sudo apt update
sudo apt upgrade -y
sudo apt autoremove -y

# ROS
read -s -n1 -p "准备安装 ROS Noetic，按任意键继续..."
echo
sudo sh -c '. /etc/lsb-release && echo "deb http://mirrors.ustc.edu.cn/ros/ubuntu/ `lsb_release -cs` main" > /etc/apt/sources.list.d/ros-latest.list'
sudo apt install -y curl
sudo apt-key add ~/openmover_robot/ros.asc
sudo apt update
sudo apt install -y ros-noetic-desktop-full
sudo apt-get install -y ros-noetic-joint-state-controller ros-noetic-position-controllers ros-noetic-navigation ros-noetic-slam-gmapping ros-noetic-robot-pose-ekf ros-noetic-teb-local-planner ros-noetic-joy ros-noetic-octomap* ros-noetic-tf2* ignition* libignition-math* libmodbus*
source /opt/ros/noetic/setup.bash
echo "source /opt/ros/noetic/setup.bash" >> ~/.bashrc
sudo apt install -y python3-rosdep python3-rosinstall python3-rosinstall-generator python3-wstool build-essential
