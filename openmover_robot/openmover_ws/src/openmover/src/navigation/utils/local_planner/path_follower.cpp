#include <navigation/utils/local_planner/path_follower.h>

path_follower::path_follower(float max_x_vel, float min_x_vel, float max_x_acc, float max_yaw_vel, float min_yaw_vel, float max_yaw_acc, bool allow_reverse_drive,
                             bool use_advanced_evaluation, bool use_kinematic_limits, bool use_find_mode_follower,
                             float velocity_dec_offset_time,
                             float find_mode_x_vel, float find_mode_yaw_vel, float find_mode_radius, float find_mode_min_dist_timeout, bool enable_near_angle_correct,
                             float angle_diff_to_forward, float angle_diff_to_rotate,
                             float xy_tolerance, float yaw_tolerance,
                             float chassis_radius,
                             float sim_time, float find_mode_sim_time, int sim_vx_space_size, int sim_vyaw_space_size, int trajectory_sim_step, float follow_point_weight, float follow_path_weight,
                             float stop_distance, float turning_stop_distance, float ignore_obstacle_dist,
                             float obstacle_acc_ratio, float collision_vel_dec_ratio,
                             int collision_plan_try_count, int collision_trajectory_sampling_ratio, int collision_path_sampling_ratio,
                             float collision_path_dist_error_tolerance, float collision_path_angle_error_tolerance,
                             float collision_obstacle_detection_area_padding_ratio, int collision_narrow_section_padding,
                             geometry_msgs::Polygon footprint,
                             float control_freq,
                             shared_ptr<planner_with_costmap> global_planner_instance,
                             int map_occupied_threshold,
                             float planner_min_dist_to_obs)
{
    set_kinematic_params(max_x_vel, max_yaw_vel);
    min_x_vel_ = min_x_vel;
    max_x_acc_ = max_x_acc;
    min_yaw_vel_ = min_yaw_vel;
    max_yaw_acc_ = max_yaw_acc;

    velocity_dec_offset_time_ = velocity_dec_offset_time;

    allow_reverse_drive_ = allow_reverse_drive;
    use_advanced_evaluation_ = use_advanced_evaluation;
    use_kinematic_limits_ = use_kinematic_limits;
    use_find_mode_follower_ = use_find_mode_follower;

    find_mode_x_vel_ = find_mode_x_vel;
    find_mode_yaw_vel_ = find_mode_yaw_vel;
    find_mode_radius_ = find_mode_radius;
    find_mode_min_dist_timeout_ = find_mode_min_dist_timeout;

    enable_near_angle_correct_ = enable_near_angle_correct;

    angle_diff_to_forward_ = angle_diff_to_forward;
    angle_diff_to_rotate_ = angle_diff_to_rotate;

    xy_tolerance_ = xy_tolerance;
    yaw_tolerance_ = yaw_tolerance;

    chassis_radius_ = chassis_radius;

    sim_time_ = sim_time;
    find_mode_sim_time_ = find_mode_sim_time;
    sim_vx_space_size_ = sim_vx_space_size;
    sim_vyaw_space_size_ = sim_vyaw_space_size;
    trajectory_sim_step_ = trajectory_sim_step;
    follow_point_weight_ = follow_point_weight;
    follow_path_weight_ = follow_path_weight;

    stop_distance_ = stop_distance;
    turning_stop_distance_ = turning_stop_distance;
    ignore_obstacle_dist_ = ignore_obstacle_dist;

    obstacle_acc_ratio_ = obstacle_acc_ratio;
    collision_vel_dec_ratio_ = collision_vel_dec_ratio;
    collision_plan_try_count_ = collision_plan_try_count;
    collision_trajectory_sampling_ratio_ = collision_trajectory_sampling_ratio;
    collision_path_sampling_ratio_ = collision_path_sampling_ratio;
    collision_path_dist_error_tolerance_ = collision_path_dist_error_tolerance;
    collision_path_angle_error_tolerance_ = collision_path_angle_error_tolerance;
    collision_obstacle_detection_area_padding_ratio_ = collision_obstacle_detection_area_padding_ratio;
    collision_narrow_section_padding_ = collision_narrow_section_padding;

    footprint_ = footprint;

    control_freq_ = control_freq;

    map_occupied_threshold_ = map_occupied_threshold;
    planner_min_dist_to_obs_ = planner_min_dist_to_obs;

    global_planner_instance_ = global_planner_instance;
    robot_pose_index_finder_id_ = 0;
    robot_pose_index_finder_instance_ = &robot_pose_index_finder_a_;
    global_planner_flag_ = false;

    state_ = navigation_state::READY;
    obstacle_state_ = block_state::CLEAR;
    last_state_ = state_;
    unable_to_find_collision_plan_flag_ = false;
    path_with_collision_markers_.clear();
    pose_out_of_collision_path_ = false;

    vx_delta_ = (1.0f / control_freq_) * max_x_acc_;
    vyaw_delta_ = (1.0f / control_freq_) * max_yaw_acc_;

    current_point_in_path_pub_ = node_handle_.advertise<geometry_msgs::PoseStamped>("current_point_in_path", 1);
    point_to_track_pub_ = node_handle_.advertise<geometry_msgs::PoseStamped>("point_to_track", 1);
    best_trajectory_pub_ = node_handle_.advertise<nav_msgs::Path>("best_trajectory", 1);
    all_trajectory_pub_ = node_handle_.advertise<nav_msgs::Path>("all_trajectory", 1);

    mover_ = unique_ptr<mover>(new mover(max_x_vel_, min_x_vel_, max_x_acc_, max_yaw_vel_, min_yaw_vel_, max_yaw_acc_,
                                         velocity_dec_offset_time_,
                                         velocity_dec_offset_time_,
                                         find_mode_min_dist_timeout_,
                                         xy_tolerance_, yaw_tolerance_, stop_distance_, 0, 0,
                                         obstacle_acc_ratio_,
                                         control_freq_));

    path_checker_ = unique_ptr<path_checker>(new path_checker);
    collision_checker_ = unique_ptr<collision_checker>(new collision_checker);

    acc_controlled_ = false;
    last_acc_controlled_ = false;

    find_mode_ = false;
    near_angle_corrected_ = false;
    stand_at_goal_ = false;

    find_mode_counter_ = 0;
    dist_ = 0;
    min_dist_ = INFINITY;

    boost::thread global_planner_thread(boost::bind(&path_follower::replan_global_plan, this));

    rotation_state_ = rotation_state::READY;
}

path_follower::~path_follower()
{
    if (mover_ != NULL)
    {
        mover_.reset();
    }

    if (path_checker_ != NULL)
    {
        path_checker_.reset();
    }

    if (collision_checker_ != NULL)
    {
        collision_checker_.reset();
    }
}

void path_follower::replan_global_plan()
{
    while (ros::ok())
    {
        ros::Duration(0.1).sleep();

        if (global_planner_flag_ && replan_flag_)
        // if (false)
        {
            geometry_msgs::PoseStamped start, goal;

            start.header.frame_id = LOCALIZATION_MAP;
            start.header.stamp = ros::Time::now();
            start.pose.orientation = (current_point_in_path_ < 10 ? plan_[0].pose.orientation : plan_[current_point_in_path_ - 10].pose.orientation);
            start.pose.position = (current_point_in_path_ < 10 ? plan_[0].pose.position : plan_[current_point_in_path_ - 10].pose.position);

            goal.header.frame_id = LOCALIZATION_MAP;
            goal.header.stamp = ros::Time::now();
            goal.pose.orientation = goal_.orientation;
            goal.pose.position = goal_.position;

            tuple<bool, vector<geometry_msgs::PoseStamped>, vector<geometry_msgs::PoseStamped>> plan_result =
                make_tuple<bool, vector<geometry_msgs::PoseStamped>, vector<geometry_msgs::PoseStamped>>(false, vector<geometry_msgs::PoseStamped>(), vector<geometry_msgs::PoseStamped>());

            if (!grid_.data.empty())
            {
                plan_result = global_planner_instance_->plan(start, goal, grid_, planner_min_dist_to_obs_, true, 1, false, 2.0, 8, map_occupied_threshold_);
            }
            else
            {
                plan_result = global_planner_instance_->plan(start, goal, planner_min_dist_to_obs_, true, 1, false, 2.0, 8, map_occupied_threshold_);
            }

            if (get<0>(plan_result) && get<1>(plan_result).size() > 2)
            {
                auto plan_new = get<1>(plan_result);

                nav_msgs::Path plan_path;
                plan_path.header = goal.header;
                plan_path.poses = plan_new;

                auto path_with_collision_markers_new = path_checker_->check(plan_path,
                                                                            footprint_,
                                                                            ignore_obstacle_ ? ignore_obstacle_dist_ : stop_distance_,
                                                                            collision_obstacle_detection_area_padding_ratio_,
                                                                            collision_narrow_section_padding_,
                                                                            collision_path_sampling_ratio_);

                if (robot_pose_index_finder_id_ == 0)
                {
                    robot_pose_index_finder_b_.set_path(plan_new, true);
                }
                else
                {
                    robot_pose_index_finder_a_.set_path(plan_new, true);
                }

                global_planner_mutex_.lock();

                plan_ = plan_new;
                path_with_collision_markers_ = path_with_collision_markers_new;

                if (robot_pose_index_finder_id_ == 0)
                {
                    robot_pose_index_finder_instance_ = &robot_pose_index_finder_b_;

                    robot_pose_index_finder_id_ = 1;
                }
                else
                {
                    robot_pose_index_finder_instance_ = &robot_pose_index_finder_a_;

                    robot_pose_index_finder_id_ = 0;
                }

                global_planner_mutex_.unlock();
            }
        }
    }
}

void path_follower::set_kinematic_params(float max_x_vel, float max_yaw_vel)
{
    max_x_vel_ = max_x_vel;
    max_yaw_vel_ = max_yaw_vel;
}

void path_follower::set_tolerance_params(float xy_tolerance, float yaw_tolerance)
{
    xy_tolerance_ = xy_tolerance;
    yaw_tolerance_ = yaw_tolerance;
}

bool path_follower::make_plan(geometry_msgs::PoseWithCovarianceStamped pose, vector<geometry_msgs::PoseStamped> plan, bool ignore_obstacle, bool replan_flag)
{
    bool ret = false;

    if (state_ == navigation_state::READY)
    {
        plan_ = plan;
        pose_ = pose;
        replan_flag_ = replan_flag;

        if (plan_.size() > 0)
        {
#if PF_DEBUG
            ROS_INFO("新导航任务已接收，路径点数量：%d。", (int)plan_.size());
#endif

            // 设置标记
            ignore_obstacle_ = ignore_obstacle;
            current_point_in_path_ = 0;
            find_mode_ = false;
            near_angle_corrected_ = false;
            stand_at_goal_ = false;
            acc_controlled_ = false;
            last_acc_controlled_ = false;
            find_mode_counter_ = 0;
            dist_ = 0;
            min_dist_ = INFINITY;
            obstacle_state_ = block_state::CLEAR;
            rotation_state_ = rotation_state::READY;
            unable_to_find_collision_plan_flag_ = false;
            path_with_collision_markers_.clear();
            pose_out_of_collision_path_ = false;

            mover_->reset_state();

            // 记录当前目标点
            goal_ = plan_[plan_.size() - 1].pose;

            // 重置最优局部路径
            current_best_trajectory_.header.frame_id = plan_[plan_.size() - 1].header.frame_id;
            current_best_trajectory_.poses.clear();

            // 预处理路径狭窄空间感知
            // 如果存在路径
            if (plan_.size() > 1)
            {
                nav_msgs::Path plan_path;
                plan_path.header = pose.header;
                plan_path.poses = plan_;

                path_with_collision_markers_ = path_checker_->check(plan_path,
                                                                    footprint_,
                                                                    ignore_obstacle_ ? ignore_obstacle_dist_ : stop_distance_,
                                                                    collision_obstacle_detection_area_padding_ratio_,
                                                                    collision_narrow_section_padding_,
                                                                    collision_path_sampling_ratio_);
            }
            else
            {
                path_with_collision_markers_.clear();

                point_with_collision_marker point{.mode_forward_drive = point_collision_mode::narrow,
                                                  .mode_reverse_drive = point_collision_mode::narrow,
                                                  .pose = plan_[plan_.size() - 1]};

                path_with_collision_markers_.push_back(point);
            }

            // 判断是否需要向后驱动
            if (allow_reverse_drive_)
            {
                reverse_drive_ = false;

                // 计算正向驱动时预先需要旋转的角度
                auto angle_to_goal = calc_goal_angle();

                // 如果正向驱动需要旋转的角度大于90度，则选择向后驱动
                if (abs(get<0>(angle_to_goal)) > M_PI / 2)
                {
#if PF_DEBUG
                    ROS_INFO("旋转角度为：%f，选择向后驱动。", get<0>(angle_to_goal));
#endif

                    reverse_drive_ = true;
                }
            }
            else
            {
                reverse_drive_ = false;
            }

            robot_pose_index_finder_id_ = 0;
            robot_pose_index_finder_instance_ = &robot_pose_index_finder_a_;
            robot_pose_index_finder_instance_->set_path(plan_, true);

            state_ = navigation_state::PROCESSING;

            ret = true;
        }
        else
        {
#if PF_DEBUG
            ROS_WARN("路径为空，无法进行导航。");
#endif
        }
    }

    return ret;
}

bool path_follower::start_session()
{
    bool ret = false;

    if (state_ == navigation_state::PROCESSING)
    {
        state_ = navigation_state::TURNING;

        ret = true;
    }

    return ret;
}

bool path_follower::pause_session()
{
    bool ret = false;

    if (state_ != navigation_state::READY &&
        state_ != navigation_state::PROCESSING &&
        state_ != navigation_state::REACHED &&
        state_ != navigation_state::PAUSING &&
        state_ != navigation_state::BLOCKED)
    {
        last_twist_target_ = twist_target_;

        last_state_ = state_;
        state_ = navigation_state::PAUSING;

        ret = true;
    }

    return ret;
}

bool path_follower::continue_session()
{
    bool ret = false;

    if (state_ == navigation_state::PAUSING)
    {
        state_ = last_state_;

        twist_target_ = last_twist_target_;

        ret = true;
    }

    return ret;
}

navigation_state path_follower::loop(geometry_msgs::PoseWithCovarianceStamped pose,
                                     geometry_msgs::TwistWithCovarianceStamped odom_twist,
                                     openmover_msgs::obstacle obstacle,
                                     geometry_msgs::Polygon footprint,
                                     nav_msgs::OccupancyGrid &grid)
{
    if (global_planner_mutex_.try_lock())
    {
        // 处理事件
        if (state_ != navigation_state::READY &&
            state_ != navigation_state::REACHED &&
            state_ != navigation_state::PROCESSING &&
            state_ != navigation_state::PAUSING)
        {
            // 更新数据
            pose_ = pose;
            odom_twist_ = odom_twist;
            obstacle_ = obstacle;
            footprint_ = footprint;
            grid_ = grid;

            // 更新机器人在全局路径中的点
            update_current_point_in_path();

            // 更新到目标点的距离
            dist_ = distance(pose_.pose.pose, goal_);

            // 第一步，旋转至接近路径方向
            if (state_ == navigation_state::TURNING &&
                obstacle_state_ == block_state::CLEAR)
            {
                if (rotation_state_ == rotation_state::READY)
                {
                    // 计算所需要的旋转角度
                    auto angle_to_global_path = calc_global_plan_angle(get_max_sim_distance_point_index());

                    // 旋转至开始行驶容差内
                    // rotate(get<0>(angle_to_global_path), yaw_tolerance_, max_yaw_vel_);
                    rotate(get<1>(angle_to_global_path), yaw_tolerance_, max_yaw_vel_, true);
                }
                else if (rotate())
                {
#if PF_DEBUG
                    ROS_INFO("全局路径跟随旋转完毕，准备开始行驶。");
#endif

                    state_ = navigation_state::STRIGHTING;
                }
            }

            // 第二步，跟随路径行驶
            if ((state_ == navigation_state::STRIGHTING &&
                 obstacle_state_ == block_state::CLEAR) ||
                (state_ == navigation_state::BLOCKED &&
                 last_state_before_blocked_ == navigation_state::STRIGHTING &&
                 unable_to_find_collision_plan_flag_))
            {
                // 若未到达目标点或仍在旋转，跟随路径行驶
                if (!stand_at_goal_ ||
                    rotation_state_ != rotation_state::READY)
                {
                    // 定义当前状态下的最大速度
                    float max_x_vel = find_mode_x_vel_;
                    float max_yaw_vel = find_mode_yaw_vel_;

                    // 定义当前状态下旋转误差
                    float yaw_tolrance = yaw_tolerance_;

                    // 定义当前状态下旋转阈值
                    float angle_to_rotate =
                        near_angle_corrected_ ? angle_diff_to_rotate_ : yaw_tolerance_;

                    // 定义最远的可模拟计算的插值点为目标点
                    int max_sim_point_index = plan_.size() - 1;

                    // 定义距离目标点的距离
                    volatile float dist = distance(goal_, pose_.pose.pose);

                    // 计算距离目标点的角度
                    auto angle = calc_goal_angle();

                    // 设置进入目标寻找模式标志
                    find_mode_ = true;

                    // 若在目标寻找半径外，则未进入目标寻找模式
                    if (dist_ > find_mode_radius_)
                    {
                        // 搜索最远的可模拟计算的插值点
                        max_sim_point_index = get_max_sim_angle_point_index(get_max_sim_distance_point_index());

                        // 设置最大速度
                        float alpha = min(max((dist_ - find_mode_radius_) / find_mode_radius_, 0.0f), 1.0f);
                        max_x_vel = find_mode_x_vel_ + alpha * (max_x_vel_ - find_mode_x_vel_);
                        max_yaw_vel = find_mode_yaw_vel_ + alpha * (max_yaw_vel_ - find_mode_yaw_vel_);

                        // 设置旋转误差
                        yaw_tolrance = angle_diff_to_forward_;

                        // 设置旋转阈值
                        angle_to_rotate = angle_diff_to_rotate_;

                        // 计算距离下一个插值点的距离
                        dist = distance(plan_[max_sim_point_index].pose, pose_.pose.pose);

                        // 计算距离下一个插值点的角度
                        angle = calc_global_plan_angle(max_sim_point_index);

                        // 当前非寻找模式
                        find_mode_counter_ = 0;
                        find_mode_ = false;
                    }

                    // 如果偏离路径过大，重新修正角度
                    if (((!find_mode_ || (find_mode_ && enable_near_angle_correct_ && !near_angle_corrected_)) && abs(get<0>(angle)) > angle_to_rotate) ||
                        rotation_state_ != rotation_state::READY)
                    {
                        // 旋转时禁止重规划
                        global_planner_flag_ = false;

                        if (rotation_state_ == rotation_state::READY)
                        {
                            // 旋转至开始行驶容差内
                            // rotate(get<0>(angle), yaw_tolrance, max_yaw_vel);
                            rotate(get<1>(angle), yaw_tolrance, max_yaw_vel, true);
                        }
                        else if (rotate())
                        {
#if PF_DEBUG
                            ROS_INFO("全局路径跟随旋转完毕，准备开始行驶。");
#endif

                            // 清除状态
                            unable_to_find_collision_plan_flag_ = false;
                            pose_out_of_collision_path_ = false;

                            if (find_mode_ && !near_angle_corrected_)
                            {
                                near_angle_corrected_ = true;
                            }

                            find_mode_counter_ = 0;
                        }
                    }
                    else
                    {
                        // 如果在寻找模式，不重规划
                        global_planner_flag_ = pose_.header.frame_id == LOCALIZATION_MAP && !find_mode_ && !stand_at_goal_;

                        // 计算新速度
                        float vx = 0, vyaw = 0;

                        // 进行航迹推算计算速度，考虑障碍通过
                        unable_to_find_collision_plan_flag_ = true;

                        // 计算是否偏离轨迹
                        float dist_to_path = distance(pose_.pose.pose, plan_[current_point_in_path_].pose);
                        float angle_to_path = angles::shortest_angular_distance(
                            angles::normalize_angle(tf::getYaw(pose_.pose.pose.orientation) + (reverse_drive_ ? M_PI : 0)),
                            tf::getYaw(path_with_collision_markers_[current_point_in_path_].pose.pose.orientation));

                        if (dist_to_path <= collision_path_dist_error_tolerance_ &&
                            abs(angle_to_path) <= collision_path_angle_error_tolerance_)
                        {
                            pose_out_of_collision_path_ = false;
                        }
                        else
                        {
                            pose_out_of_collision_path_ = true;
                        }

                        // 判断当前点避障模式
                        point_collision_mode path_point_mode =
                            reverse_drive_ ? path_with_collision_markers_[current_point_in_path_].mode_reverse_drive : path_with_collision_markers_[current_point_in_path_].mode_forward_drive;

                        for (int i = 0; i < collision_plan_try_count_; i++)
                        {
                            // 生成该线速度下最优轨迹
                            auto current_traj = trajectory_simulation(vx, vyaw,
                                                                      max_sim_point_index,
                                                                      max_x_vel, max_yaw_vel,
                                                                      find_mode_ ? find_mode_sim_time_ : sim_time_);

                            // 检查障碍
                            if (ignore_obstacle_ ||
                                (path_point_mode == point_collision_mode::normal && !pose_out_of_collision_path_) ||
                                !get<0>(collision_checker_->check(pose_, pose_, footprint_, current_traj, obstacle_, collision_trajectory_sampling_ratio_)))
                            {
                                unable_to_find_collision_plan_flag_ = false;

                                break;
                            }
                            else
                            {
                                // 减速放缩尝试
                                max_x_vel /= collision_vel_dec_ratio_;

                                if (max_x_vel <= min_x_vel_)
                                {
                                    break;
                                }
                            }
                        }

                        if (!unable_to_find_collision_plan_flag_)
                        {
                            // 若超过运动学特性，进行动态速度分配
                            if (use_kinematic_limits_)
                            {
                                volatile float combined_vel = abs(vx) + abs(vyaw * chassis_radius_);

                                if (combined_vel > max_x_vel)
                                {
                                    volatile float vel_factor = max_x_vel / combined_vel;
                                    vx *= vel_factor;
                                    vyaw *= vel_factor;
                                }
                            }

                            // 防止丢失线速度，永远无法到达
                            if (abs(vx) < min_x_vel_)
                            {
                                vx = copysign(min_x_vel_, vx);
                            }

                            // 设置计算速度为目标速度
                            twist_target_.linear.x = vx;
                            twist_target_.angular.z = vyaw;

#if PF_DEBUG
                            // ROS_INFO("误差：%f，线速度：%f，角速度：%f。",
                            //          dist_, vx, vyaw);
#endif

                            // 寻找超时计数器
                            if (find_mode_ &&
                                ((abs(odom_twist_.twist.twist.linear.x) >= min_x_vel_ / 2.0f ||
                                  abs(odom_twist_.twist.twist.angular.z) >= min_yaw_vel_ / 2.0f)) &&
                                dist_ > min_dist_)
                            {
                                find_mode_counter_++;
                            }
                            else
                            {
                                find_mode_counter_ = 0;
                            }

                            // 如果到达直线容差，则认为已经在目标点停止
                            if (find_mode_counter_ >= (int)abs(find_mode_min_dist_timeout_ * control_freq_) ||
                                dist_ <= xy_tolerance_)
                            {
                                stand_at_goal_ = true;
                            }
                        }
                    }
                }
                // 若到达目标点，转向至正确方向
                else
                {
#if PF_DEBUG
                    ROS_INFO("全局路径跟随行驶完毕，准备调整最终角度。");
#endif

                    acc_controlled_ = true;
                    twist_target_.linear.x = 0;
                    twist_target_.angular.z = 0;

                    global_planner_flag_ = false;

                    state_ = navigation_state::TURNING_RECOVERY;
                }
            }

            // 第三步，调整角度
            if (state_ == navigation_state::TURNING_RECOVERY &&
                obstacle_state_ == block_state::CLEAR)
            {
                global_planner_flag_ = false;

                // 最终角度调整
                if (rotation_state_ == rotation_state::READY)
                {
                    // 注意此处，无论是否向后驱动，最终朝向角均以正方向为准。
                    float angle_to_goal = (float)angles::shortest_angular_distance(
                        tf::getYaw(pose_.pose.pose.orientation), tf::getYaw(goal_.orientation));
                    float goal_yaw = tf::getYaw(goal_.orientation);

                    // 旋转至最终角度容差内
                    // rotate(angle_to_goal, yaw_tolerance_, max_yaw_vel_);
                    rotate(goal_yaw, yaw_tolerance_, max_yaw_vel_, true);
                }
                else if (rotate())
                {
#if PF_DEBUG
                    ROS_INFO("最终角度调整完毕，导航结束。");
#endif

                    acc_controlled_ = true;
                    twist_target_.linear.x = 0;
                    twist_target_.angular.z = 0;

                    global_planner_flag_ = false;

                    obstacle_state_ = block_state::CLEAR;
                    state_ = navigation_state::REACHED;
                }
            }
            else if (state_ == navigation_state::BLOCKED &&
                     obstacle_state_ == block_state::CLEAR)
            {
                twist_target_ = last_twist_target_;
                vx_delta_ /= obstacle_acc_ratio_;
                vyaw_delta_ /= obstacle_acc_ratio_;
                acc_controlled_ = last_acc_controlled_;
                state_ = last_state_before_blocked_;
                global_planner_flag_ = pose_.header.frame_id == LOCALIZATION_MAP && !find_mode_ && !stand_at_goal_;
            }
            else if (state_ != navigation_state::BLOCKED &&
                     obstacle_state_ != block_state::CLEAR)
            {
                last_twist_target_ = twist_target_;

                vx_delta_ *= obstacle_acc_ratio_;
                vyaw_delta_ *= obstacle_acc_ratio_;

                twist_target_.linear.x = 0;
                twist_target_.angular.z = 0;

                last_acc_controlled_ = acc_controlled_;
                acc_controlled_ = false;

                last_state_before_blocked_ = state_;

                // global_planner_flag_ = pose_.header.frame_id == LOCALIZATION_MAP && !find_mode_ && !stand_at_goal_;

                global_planner_flag_ = false;

                state_ = navigation_state::BLOCKED;
            }

            // 更新最小距离
            min_dist_ = min(dist_, min_dist_);

            // 检测障碍物
            if (unable_to_find_collision_plan_flag_)
            {
                obstacle_state_ = reverse_drive_ ? block_state::BACKWARD : block_state::FORWARD;
            }
            else
            {
                obstacle_state_ = is_obstacle_detected();
            }
        }
        else if (state_ == navigation_state::PAUSING)
        {
            twist_target_.linear.x = 0;
            twist_target_.angular.z = 0;

            global_planner_flag_ = false;
        }

        global_planner_mutex_.unlock();
    }
    else
    {
        obstacle_state_ = is_obstacle_detected();

        if (state_ != navigation_state::BLOCKED &&
            obstacle_state_ != block_state::CLEAR)
        {
            last_twist_target_ = twist_target_;

            vx_delta_ *= obstacle_acc_ratio_;
            vyaw_delta_ *= obstacle_acc_ratio_;

            twist_target_.linear.x = 0;
            twist_target_.angular.z = 0;

            last_acc_controlled_ = acc_controlled_;
            acc_controlled_ = false;

            last_state_before_blocked_ = state_;

            // global_planner_flag_ = pose_.header.frame_id == LOCALIZATION_MAP && !find_mode_ && !stand_at_goal_;

            global_planner_flag_ = false;

            state_ = navigation_state::BLOCKED;
        }
    }

    return state_;
}

void path_follower::update_current_point_in_path()
{
    // float min_dist_to_base = INFINITY;

    // // 向前搜索
    // for (int i = current_point_in_path_; i < plan_.size(); i++)
    // {
    //     float dist = distance(plan_[i].pose, pose_.pose.pose);

    //     // 判断路径中的点距离是否更接近机器人本体
    //     if (dist < min_dist_to_base)
    //     {
    //         current_point_in_path_ = i;
    //         min_dist_to_base = dist;
    //     }

    //     // 搜索终点
    //     if (dist >= sim_time_ * max_x_vel_)
    //     {
    //         break;
    //     }
    // }

    // // 向后搜索
    // for (int i = current_point_in_path_; i >= 0; i--)
    // {
    //     float dist = distance(plan_[i].pose, pose_.pose.pose);

    //     // 判断路径中的点距离是否更接近机器人本体
    //     if (dist < min_dist_to_base)
    //     {
    //         current_point_in_path_ = i;
    //         min_dist_to_base = dist;
    //     }

    //     // 搜索终点
    //     if (dist >= sim_time_ * max_x_vel_)
    //     {
    //         break;
    //     }
    // }

    current_point_in_path_ = robot_pose_index_finder_instance_->get_index(pose_);

    // 发布点
    current_point_in_path_pub_.publish(plan_[current_point_in_path_]);
}

bool path_follower::rotate(float angle, float tolerance, float max_yaw_vel, bool yaw_servo_mode)
{
    bool ret = false;

    if (rotation_state_ == rotation_state::READY)
    {
        // 调整角度前先停车
        twist_target_.linear.x = 0;
        twist_target_.angular.z = 0;

        if (abs(odom_twist_.twist.twist.linear.x) <= vx_delta_ / 2.0f &&
            abs(odom_twist_.twist.twist.angular.z) <= vyaw_delta_ / 2.0f)
        {
            // 设置旋转参数
            mover_->reset_state();
            mover_->set_kinematic_params(max_x_vel_, max_yaw_vel);
            mover_->set_tolerance_params(xy_tolerance_, tolerance);

            // 规划旋转速度
            mover_->make_plan(pose_, 0, angle, true, yaw_servo_mode);

            // 开始旋转
            mover_->start_session();

            // 设置加速控制为外部接管模式
            acc_controlled_ = true;

            rotation_state_ = rotation_state::RUNNING;
        }
    }
    else if (rotation_state_ == rotation_state::RUNNING)
    {
        // 处理旋转控制事件
        auto state = mover_->loop(pose_, odom_twist_, obstacle_);

        // 如果旋转状态为到达
        if (state == navigation_state::REACHED)
        {
            // 重置旋转控制器
            mover_->reset_state();

            // 机器人停车
            twist_target_.linear.x = 0;
            twist_target_.angular.z = 0;

            rotation_state_ = rotation_state::REACHED;
        }
        else
        {
            twist_target_ = mover_->get_current_twist();
        }
    }
    else if (rotation_state_ == rotation_state::REACHED)
    {
        // 等待机器人彻底停车
        // ros::Duration((min_yaw_vel_ * 2.0f) / max_yaw_acc_).sleep();

        // 设置加速度控制为内部模式
        acc_controlled_ = false;

        // 恢复状态
        rotation_state_ = rotation_state::READY;

#if PF_DEBUG
        ROS_INFO("旋转状态已经重置。");
#endif

        ret = true;
    }

    return ret;
}

geometry_msgs::Twist path_follower::get_current_twist()
{
    // 如果加速度为外部接管模式
    if (acc_controlled_)
    {
        // 速度为目标速度
        twist_.linear.x = twist_target_.linear.x;
        twist_.angular.z = twist_target_.angular.z;
    }
    // 否则进行加减速控制
    else
    {
        // 控制线速度
        if (odom_twist_.twist.twist.linear.x < twist_target_.linear.x)
        {
            twist_.linear.x += vx_delta_;

            if (twist_.linear.x > twist_target_.linear.x)
            {
                twist_.linear.x = twist_target_.linear.x;
            }
        }
        else if (odom_twist_.twist.twist.linear.x > twist_target_.linear.x)
        {
            twist_.linear.x -= vx_delta_;

            if (twist_.linear.x < twist_target_.linear.x)
            {
                twist_.linear.x = twist_target_.linear.x;
            }
        }

        // 控制角速度
        if (odom_twist_.twist.twist.angular.z < twist_target_.angular.z)
        {
            twist_.angular.z += vyaw_delta_;

            if (twist_.angular.z > twist_target_.angular.z)
            {
                twist_.angular.z = twist_target_.angular.z;
            }
        }
        else if (odom_twist_.twist.twist.angular.z > twist_target_.angular.z)
        {
            twist_.angular.z -= vyaw_delta_;

            if (twist_.angular.z < twist_target_.angular.z)
            {
                twist_.angular.z = twist_target_.angular.z;
            }
        }
    }

    return twist_;
}

geometry_msgs::PoseWithCovarianceStamped path_follower::get_current_pose()
{
    return pose_;
}

geometry_msgs::PoseStamped path_follower::get_current_path_point_pose()
{
    return plan_[current_point_in_path_];
}

block_state path_follower::get_obstacle_state()
{
    return obstacle_state_;
}

void path_follower::reset_state()
{
    twist_target_.linear.x = 0;
    twist_target_.angular.z = 0;
    current_point_in_path_ = 0;
    obstacle_state_ = block_state::CLEAR;
    state_ = navigation_state::READY;
}

int path_follower::get_max_sim_distance_point_index()
{
    int ret = -1;

    // 在路径中寻找模拟时间内可预计算的距离最远点
    for (int i = current_point_in_path_; i < plan_.size(); i++)
    {
        // 计算当前位姿到全局路径中点的距离
        float dist = distance(pose_.pose.pose, plan_[i].pose);

        if (dist > max_x_vel_ * sim_time_)
        {
            ret = (i <= 0 ? 0 : (i - 1));

            break;
        }
    }

    // 如果未在路径中找到，则为路径中最后一个点
    if (ret == -1)
    {
        ret = plan_.size() - 1;
        ret = ret < 0 ? 0 : ret;
    }

    return ret;
}

int path_follower::get_max_sim_angle_point_index(int point_index)
{
    int ret = point_index;

    // 在路径中寻找模拟时间内可预计算的角度最远点
    for (int i = point_index; i >= current_point_in_path_; i--)
    {
        // 计算当前位姿到全局路径中点的距离
        auto angle = calc_global_plan_angle(i);

        if (abs(get<0>(angle)) <= max_yaw_vel_ * sim_time_)
        {
            ret = i;
            break;
        }
    }

    // 发布点
    point_to_track_pub_.publish(plan_[ret]);

    return ret;
}

tuple<float, float> path_follower::calc_goal_angle()
{
    tuple<float, float> ret(0, 0);

    // 获取当前航向角
    float current_yaw = angles::normalize_angle(
        tf::getYaw(pose_.pose.pose.orientation) + (reverse_drive_ ? M_PI : 0));

    // 获取到该点的直行角度
    float angle_to_goal = atan2(goal_.position.y - pose_.pose.pose.position.y,
                                goal_.position.x - pose_.pose.pose.position.x);

    // 计算到全局路径的角度差
    get<0>(ret) = (float)angles::shortest_angular_distance(current_yaw, angle_to_goal);
    get<1>(ret) = (float)angles::normalize_angle(current_yaw + angle_to_goal - (reverse_drive_ ? M_PI : 0));

    return ret;
}

tuple<float, float> path_follower::calc_global_plan_angle(int point_index)
{
    tuple<float, float> ret(0, 0);

    if (plan_.size() <= 1)
    {
        return calc_goal_angle();
    }

    // 获取当前航向角
    float current_yaw = angles::normalize_angle(
        tf::getYaw(pose_.pose.pose.orientation) + (reverse_drive_ ? M_PI : 0));

    float sum_sin = 0;
    float sum_cos = 0;
    int point_num = 0;

    for (int i = current_point_in_path_; i <= point_index; i++)
    {
        // 获取到该点的直行角度
        float angle_to_point =
            (float)angles::shortest_angular_distance(current_yaw, atan2(plan_[i].pose.position.y - pose_.pose.pose.position.y,
                                                                        plan_[i].pose.position.x - pose_.pose.pose.position.x));

        // 累加角度的正弦和余弦值
        sum_sin += sin(angle_to_point);
        sum_cos += cos(angle_to_point);

        point_num++;
    }

    if (point_num > 0)
    {
        // 计算平均角度
        get<0>(ret) = atan2(sum_sin / point_num, sum_cos / point_num);
        get<1>(ret) = (float)angles::normalize_angle(current_yaw + get<0>(ret) - (reverse_drive_ ? M_PI : 0));
    }
    else
    {
        get<0>(ret) = 0;
        get<1>(ret) = 0;
    }

    return ret;
}

nav_msgs::Path path_follower::trajectory_simulation(float &vx, float &vyaw,
                                                    int max_sim_point_index,
                                                    float max_x_vel, float max_yaw_vel,
                                                    float sim_time)
{
    // 定义最优轨迹
    nav_msgs::Path best_trajectory;
    float best_score_global = -std::numeric_limits<float>::infinity();

    // 计算到下一个插值点的距离
    float dist = distance(plan_[max_sim_point_index].pose, pose_.pose.pose);

    // 获取当前航向角
    float current_yaw = tf::getYaw(pose_.pose.pose.orientation);

    // 设置搜索线速度范围
    float current_vx = odom_twist_.twist.twist.linear.x;
    float start_search_vx = std::max(min_x_vel_, current_vx - sim_time * max_x_acc_);
    float end_search_vx = std::max(start_search_vx,
                                   std::min(current_vx + sim_time * max_x_acc_,
                                            dist / sim_time));

    // 若反向运行，需要对速度取反
    start_search_vx *= (reverse_drive_ ? -1.0f : 1.0f);
    end_search_vx *= (reverse_drive_ ? -1.0f : 1.0f);

    // 搜索离散步长
    float delta_search_vx = (end_search_vx - start_search_vx) /
                            (sim_vx_space_size_ <= 0 ? 1 : sim_vx_space_size_);

    // 设置角速度搜索范围
    float current_vyaw = odom_twist_.twist.twist.angular.z;
    float start_search_vyaw = current_vyaw - sim_time * max_yaw_acc_;
    float end_search_vyaw = current_vyaw + sim_time * max_yaw_acc_;

    float delta_search_vyaw = (end_search_vyaw - start_search_vyaw) /
                              (sim_vyaw_space_size_ <= 0 ? 1 : sim_vyaw_space_size_);

    // 计算单步仿真时长
    float delta_sim_time = sim_time / (trajectory_sim_step_ <= 0 ? 1 : trajectory_sim_step_);

    // 计算速度逼近过程中的单步加速度
    float delta_current_search_vx = max_x_acc_ * delta_sim_time;
    float delta_current_search_vyaw = max_yaw_acc_ * delta_sim_time;

    std::vector<std::pair<int, int>> search_pairs;

    search_pairs.reserve((sim_vx_space_size_ + 1) * (sim_vyaw_space_size_ + 1));

    for (int i = -1; i < sim_vx_space_size_; i++)
    {
        for (int j = -1; j < sim_vyaw_space_size_; j++)
        {
            search_pairs.emplace_back(i, j);
        }
    }

    struct local_result
    {
        float score;
        nav_msgs::Path traj;
        float vx;
        float vyaw;
    };

    std::vector<local_result> results(search_pairs.size());

#pragma omp parallel for
    for (int idx = 0; idx < static_cast<int>(search_pairs.size()); idx++)
    {
        int i = search_pairs[idx].first;
        int j = search_pairs[idx].second;

        float target_search_vx = 0.0f;

        if (i == -1)
        {
            target_search_vx = 0.0f;
        }
        else if (i == 0)
        {
            target_search_vx = start_search_vx;
        }
        else
        {
            target_search_vx = start_search_vx + i * delta_search_vx;
        }

        float target_search_vyaw = 0.0f;

        if (j == -1)
        {
            target_search_vyaw = 0.0f;
        }
        else if (j == 0)
        {
            target_search_vyaw = start_search_vyaw;
        }
        else
        {
            target_search_vyaw = start_search_vyaw + j * delta_search_vyaw;
        }

        // 为了使用运动学限制，需要以当前速度为起点逐步逼近
        float current_search_vx = use_kinematic_limits_ ? odom_twist_.twist.twist.linear.x : target_search_vx;
        float current_search_vyaw = use_kinematic_limits_ ? odom_twist_.twist.twist.angular.z : target_search_vyaw;
        float last_search_vx = current_search_vx;
        float last_search_vyaw = current_search_vyaw;

        // 在推算过程中累加的相对角度
        float rotated_sim_yaw = 0.0f;

        // 构造当前候选轨迹
        nav_msgs::Path current_trajectory;

        current_trajectory.poses.clear();
        {
            geometry_msgs::PoseStamped current_pose;
            current_pose.pose = pose_.pose.pose;
            current_trajectory.poses.push_back(current_pose);
        }

        for (int k = 0; k < trajectory_sim_step_; k++)
        {
            if (use_kinematic_limits_)
            {
                if (current_search_vx < target_search_vx)
                {
                    current_search_vx += delta_current_search_vx;

                    if (current_search_vx > target_search_vx)
                        current_search_vx = target_search_vx;
                }
                else if (current_search_vx > target_search_vx)
                {
                    current_search_vx -= delta_current_search_vx;

                    if (current_search_vx < target_search_vx)
                        current_search_vx = target_search_vx;
                }

                if (current_search_vyaw < target_search_vyaw)
                {
                    current_search_vyaw += delta_current_search_vyaw;

                    if (current_search_vyaw > target_search_vyaw)
                        current_search_vyaw = target_search_vyaw;
                }
                else if (current_search_vyaw > target_search_vyaw)
                {
                    current_search_vyaw -= delta_current_search_vyaw;

                    if (current_search_vyaw < target_search_vyaw)
                        current_search_vyaw = target_search_vyaw;
                }
            }

            // 计算推算位置
            geometry_msgs::PoseStamped current_sim_pose;
            current_sim_pose.pose.orientation = tf::createQuaternionMsgFromYaw(0);

            current_sim_pose.pose.position.x =
                current_trajectory.poses[k].pose.position.x +
                (((last_search_vx + current_search_vx) / 2.0f) * delta_sim_time) *
                    std::cos(current_yaw + rotated_sim_yaw);

            current_sim_pose.pose.position.y =
                current_trajectory.poses[k].pose.position.y +
                (((last_search_vx + current_search_vx) / 2.0f) * delta_sim_time) *
                    std::sin(current_yaw + rotated_sim_yaw);

            // 更新旋转角度
            rotated_sim_yaw += ((last_search_vyaw + current_search_vyaw) / 2.0f) * delta_sim_time;

            // 赋值姿态
            current_sim_pose.pose.orientation =
                tf::createQuaternionMsgFromYaw(current_yaw + rotated_sim_yaw);

            // 更新上一帧速度
            last_search_vx = current_search_vx;
            last_search_vyaw = current_search_vyaw;

            // 保存该推算点
            current_trajectory.poses.push_back(current_sim_pose);
        }

        float dist_to_point = distance(
            current_trajectory.poses.back().pose,
            plan_[max_sim_point_index].pose);

        float current_score = 0.0f;

        // 若在寻找模式或路径只剩最后一个点，则只考虑与该点的距离
        if ((use_find_mode_follower_ && find_mode_) || max_sim_point_index == (int)plan_.size() - 1)
        {
            current_score = 1.0f / (follow_point_weight_ * dist_to_point);
        }
        else
        {
            float mean_dist_to_path = (use_advanced_evaluation_ ? 0.0f : std::numeric_limits<float>::infinity());

            if (!use_advanced_evaluation_)
            {
                for (int k = current_point_in_path_; k < (int)plan_.size(); k++)
                {
                    float dist_ = distance(
                        current_trajectory.poses.back().pose,
                        plan_[k].pose);
                    mean_dist_to_path = std::min(mean_dist_to_path, dist_);

                    if (dist_ > max_x_vel * sim_time)
                        break;
                }
            }
            else
            {
                float min_dist_to_path = std::numeric_limits<float>::infinity();

                int end_point_in_path = current_point_in_path_;

                for (int k = current_point_in_path_; k < (int)plan_.size(); k++)
                {
                    float dist_ = distance(
                        current_trajectory.poses.back().pose,
                        plan_[k].pose);

                    if (dist_ <= min_dist_to_path)
                    {
                        end_point_in_path = k;
                        min_dist_to_path = dist_;
                    }

                    if (dist_ > max_x_vel * sim_time)
                        break;
                }

                // 均匀分布求平均距离
                float index_increment_ratio =
                    1.0f * (end_point_in_path - current_point_in_path_ + 1) /
                    (current_trajectory.poses.size() + 1);

                float path_point_index_raw = current_point_in_path_;
                int path_point_index = current_point_in_path_;
                int trajectory_point_index = 0;
                int dist_counter = 0;

                mean_dist_to_path = 0.0f;

                while (path_point_index <= end_point_in_path &&
                       trajectory_point_index < (int)current_trajectory.poses.size())
                {
                    mean_dist_to_path += distance(
                        plan_[path_point_index].pose,
                        current_trajectory.poses[trajectory_point_index].pose);

                    dist_counter++;

                    path_point_index_raw += index_increment_ratio;
                    path_point_index = (int)path_point_index_raw;
                    trajectory_point_index++;
                }

                if (dist_counter > 0)
                    mean_dist_to_path /= dist_counter;
            }

            float denom =
                (follow_point_weight_ * dist_to_point +
                 follow_path_weight_ * mean_dist_to_path) /
                (follow_point_weight_ + follow_path_weight_ + 1e-5f);

            current_score = 1.0f / denom;
        }

        results[idx].score = current_score;
        results[idx].traj = current_trajectory;
        results[idx].vx = target_search_vx;
        results[idx].vyaw = target_search_vyaw;
    }

    {
        int index_count = 0;

        for (int i = -1; i < sim_vx_space_size_; i++)
        {
            for (int j = -1; j < sim_vyaw_space_size_; j++)
            {
                auto &r = results[index_count];

                r.traj.header.stamp = ros::Time::now();
                r.traj.header.frame_id = current_best_trajectory_.header.frame_id;

                all_trajectory_pub_.publish(r.traj);

                index_count++;
            }
        }
    }

    for (auto &r : results)
    {
        if (r.score >= best_score_global)
        {
            best_score_global = r.score;
            best_trajectory = r.traj;
            vx = r.vx;
            vyaw = r.vyaw;
        }
    }

    current_best_trajectory_.header.stamp = ros::Time::now();
    current_best_trajectory_.poses = best_trajectory.poses;
    best_trajectory_pub_.publish(current_best_trajectory_);

    return best_trajectory;
}

block_state path_follower::is_obstacle_detected()
{
    block_state ret = block_state::CLEAR;

    // 对于线速度
    if (max(abs(twist_target_.linear.x), abs(last_twist_target_.linear.x)) >= vx_delta_ / 2)
    {
        // 如果忽略障碍物，则为忽略模式停车距离，如果路径点为普通模式，则为普通模式停车距离
        float obstacle_dist = stop_distance_;

        // 判断当前点避障模式
        point_collision_mode path_point_mode =
            reverse_drive_ ? path_with_collision_markers_[current_point_in_path_].mode_reverse_drive : path_with_collision_markers_[current_point_in_path_].mode_forward_drive;

        if (ignore_obstacle_ ||
            path_point_mode == point_collision_mode::narrow ||
            pose_out_of_collision_path_)
        {
            obstacle_dist = ignore_obstacle_dist_;
        }

        if (max(last_twist_target_.linear.x, twist_target_.linear.x) > 0)
        {
            for (int i = 0; i < obstacle_.size; i++)
            {
                if (obstacle_.obstacle_forward[i] > 0 &&
                    obstacle_.obstacle_forward[i] < obstacle_dist &&
                    obstacle_.obstacle_forward[i] < distance(pose_.pose.pose, goal_))
                {
                    ret = block_state::FORWARD;
                    break;
                }
            }
        }
        else
        {
            for (int i = 0; i < obstacle_.size; i++)
            {
                if (obstacle_.obstacle_backward[i] > 0 &&
                    obstacle_.obstacle_backward[i] < obstacle_dist &&
                    obstacle_.obstacle_backward[i] < distance(pose_.pose.pose, goal_))
                {
                    ret = block_state::BACKWARD;
                    break;
                }
            }
        }
    }
    else if (max(abs(twist_target_.angular.z), abs(last_twist_target_.angular.z)) >= vyaw_delta_ / 2)
    {
        if (max(last_twist_target_.angular.z, twist_target_.angular.z) > 0)
        {
            for (int i = 0; i < obstacle_.size; i++)
            {
                if (obstacle_.obstacle_left[i] > 0 &&
                    obstacle_.obstacle_left[i] < (ignore_obstacle_ ? ignore_obstacle_dist_ : turning_stop_distance_))
                {
                    ret = block_state::LEFT;
                    break;
                }
            }
        }
        else
        {
            for (int i = 0; i < obstacle_.size; i++)
            {
                if (obstacle_.obstacle_right[i] > 0 &&
                    obstacle_.obstacle_right[i] < (ignore_obstacle_ ? ignore_obstacle_dist_ : turning_stop_distance_))
                {
                    ret = block_state::RIGHT;
                    break;
                }
            }
        }
    }

    return ret;
}

float path_follower::distance(geometry_msgs::Pose pose0, geometry_msgs::Pose pose1)
{
    float ret = 0;

    ret = sqrt(pow(pose0.position.x - pose1.position.x, 2) +
               pow(pose0.position.y - pose1.position.y, 2) +
               pow(pose0.position.z - pose1.position.z, 2));

    return ret;
}