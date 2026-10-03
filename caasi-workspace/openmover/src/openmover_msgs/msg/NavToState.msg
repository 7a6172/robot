# 2022-3-9 0.0.0.1A

# 头数据
std_msgs/Header header
# 状态码
string state
# 当前位姿
geometry_msgs/PoseWithCovariance pose
# 当前速度
geometry_msgs/TwistWithCovariance twist
geometry_msgs/TwistWithCovariance cmd_twist
# 自定义数据格式
openmover_msgs/Pose pos
openmover_msgs/Twist vel
openmover_msgs/Twist cmd_vel
# 障碍位置数据
bool[4] obstacle