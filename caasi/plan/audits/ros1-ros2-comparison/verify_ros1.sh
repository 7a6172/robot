#!/bin/bash
# Verify the ROS 1 OpenMover reference reaches a USABLE OPERATIONAL STATE.
# Passing a build is not sufficient evidence.
export DISABLE_ROS1_EOL_WARNINGS=1
source /opt/ros/noetic/setup.bash
source /root/openmover_robot/cartographer_ws/install_isolated/setup.bash
source /root/openmover_robot/openmover_ws/devel/setup.bash
export PYTHONPATH=$PYTHONPATH:/root/openmover_robot/openmover_ws/src/openmover/scripts/hal

echo "=========== 1. All 9 packages discoverable? ==========="
for p in openmover openmover_msgs bluesea2 ira_laser_tools warehouse_simulation \
         auto_mapping_toolbox auto_mapping_toolbox_msgs \
         relocalization_toolbox relocalization_toolbox_msgs; do
  printf "  %-32s " "$p"
  rospack find "$p" 2>/dev/null || echo "NOT FOUND"
done

echo
echo "=========== 2. Custom messages generated (rosmsg) ==========="
rosmsg list 2>/dev/null | grep -c "^openmover_msgs/" | sed 's/^/  openmover_msgs types: /'
rossrv list 2>/dev/null | grep -c "^openmover_msgs/" | sed 's/^/  openmover_msgs srv:   /'
rosmsg show openmover_msgs/obstacle 2>&1 | head -5

echo
echo "=========== 3. C++ nodes built (executables) ==========="
ls /root/openmover_robot/openmover_ws/devel/lib/openmover/ 2>/dev/null

echo
echo "=========== 4. Python nodes present ==========="
ls /root/openmover_robot/openmover_ws/src/openmover/scripts/server/ 2>/dev/null

echo
echo "=========== 5. HAL imports under ROS 1 ==========="
python3 -c "
import sys
sys.path.insert(0, '/root/openmover_robot/openmover_ws/src/openmover/scripts/hal')
import config, symbols, protocol, utils, logger
print('  HAL modules import OK: config, symbols, protocol, utils, logger')
" 2>&1 | tail -5

echo
echo "=========== 6. Cartographer integration ==========="
printf "  cartographer_node:        "; ls /root/openmover_robot/cartographer_ws/install_isolated/lib/cartographer_ros/cartographer_node 2>/dev/null || echo MISSING
printf "  occupancy_grid_node:      "; ls /root/openmover_robot/cartographer_ws/install_isolated/lib/cartographer_ros/cartographer_occupancy_grid_node 2>/dev/null || echo MISSING
