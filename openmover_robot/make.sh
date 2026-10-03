cd ~/openmover_robot/cartographer_ws
catkin_make_isolated --install --use-ninja
source ~/openmover_robot/cartographer_ws/install_isolated/setup.bash
cd ~/openmover_robot/openmover_ws
catkin_make -DCATKIN_WHITELIST_PACKAGES=warehouse_simulation
catkin_make -DCATKIN_WHITELIST_PACKAGES=ira_laser_tools
catkin_make -DCATKIN_WHITELIST_PACKAGES=relocalization_toolbox_msgs
catkin_make -DCATKIN_WHITELIST_PACKAGES=relocalization_toolbox
catkin_make -DCATKIN_WHITELIST_PACKAGES=openmover_msgs
source ~/openmover_robot/openmover_ws/devel/setup.bash
catkin_make -DCATKIN_WHITELIST_PACKAGES=auto_mapping_toolbox_msgs
catkin_make -DCATKIN_WHITELIST_PACKAGES=auto_mapping_toolbox
source ~/openmover_robot/openmover_ws/devel/setup.bash
catkin_make -DCATKIN_WHITELIST_PACKAGES=bluesea2
source ~/openmover_robot/openmover_ws/devel/setup.bash
catkin_make -DCATKIN_WHITELIST_PACKAGES=openmover
catkin_make install
source ~/openmover_robot/openmover_ws/devel/setup.bash
