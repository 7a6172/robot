#include <utils/auto_mapping/local_exploration.h>
#include <utils/topic_utils.h>

namespace local_exploration
{
    local_explorer::local_explorer(const float &min_expand_dist, const float &max_expand_dist, const float &min_dist_to_obs,
                                   const float &rrt_coverage_check_density,
                                   const float &frontier_points_min_dist, const float &sensing_radius,
                                   const int &free_threshold, const int &occupied_threshold)
    {
        random_device_ = make_unique<random_device>();
        random_generator_ = make_unique<mt19937>((*random_device_)());
        gen_random_number_ = make_unique<uniform_real_distribution<float>>(0.0f, 1.0f);

        free_threshold_ = free_threshold;
        occupied_threshold_ = occupied_threshold - 1;

        min_expand_dist_ = min_expand_dist;
        max_expand_dist_ = max_expand_dist;
        min_dist_to_obs_ = min_dist_to_obs;
        rrt_coverage_check_density_ = rrt_coverage_check_density;
        frontier_points_min_dist_ = frontier_points_min_dist;
        sensing_radius_ = sensing_radius;
    }

    void local_explorer::initialize(rclcpp::Node::SharedPtr node)
    {
        node_ = node;

        tf_buffer_ = make_unique<tf2_ros::Buffer>(node_->get_clock());
        tf_listener_ = make_unique<tf2_ros::TransformListener>(*tf_buffer_, node_, true);

        for (int i = 0; i < 5; i++)
        {
            try
            {
                tf_map_to_base_link_ = tf_buffer_->lookupTransform(
                    LOCALIZATION_MAP,
                    LOCALIZATION_BASE_LINK,
                    tf2::TimePointZero, tf2::durationFromSec(60.0));
            }
            catch (...)
            {
                cout << "no tf data from map to base_link." << endl;
            }
        }

        try
        {
            auto grid = topic_utils::wait_for_message<nav_msgs::msg::OccupancyGrid>(
                node_.get(), "map", std::chrono::duration<double>(60.0));

            if (grid != NULL)
            {
                map_data_ = *grid;
            }
        }
        catch (...)
        {
            cout << "could not get global map." << endl;

            return;
        }

        min_dist_to_obs_table_ = calc_min_dist_to_obs_table(map_data_, occupied_threshold_);

        rrt_node_marker_array_pub_ = node_->create_publisher<visualization_msgs::msg::MarkerArray>("local_exploration_nodes", 5);
        rrt_frontier_node_marker_array_pub_ = node_->create_publisher<visualization_msgs::msg::MarkerArray>("local_exploration_frontier_nodes", 5);
        rrt_line_marker_array_pub_ = node_->create_publisher<visualization_msgs::msg::MarkerArray>("local_exploration_lines", 5);
        rrt_sensing_circle_pub_ = node_->create_publisher<visualization_msgs::msg::MarkerArray>("local_sensing_circle", 5);
        rrt_exploration_circle_pub_ = node_->create_publisher<visualization_msgs::msg::MarkerArray>("local_exploration_circle", 5);

        cout << "local exploration initialized." << endl;
    }

    rrt_nodes local_explorer::get_frontier_points(const int &timeout_secs)
    {
        rrt_tree_.indices.clear();
        rrt_tree_.points.clear();
        rrt_tree_.prev_indices.clear();
        rrt_tree_.prev_points.clear();
        rrt_tree_.next_indices.clear();
        rrt_tree_.next_points.clear();
        rrt_tree_.info_gains.clear();
        rrt_tree_.del_states.clear();

        frontier_points_.indices.clear();
        frontier_points_.points.clear();
        frontier_points_.prev_indices.clear();
        frontier_points_.prev_points.clear();
        frontier_points_.next_indices.clear();
        frontier_points_.next_points.clear();
        frontier_points_.info_gains.clear();
        frontier_points_.del_states.clear();

        node_index_ = 0;

        rtree_points_.clear();
        rtree_points_.emplace_back(origin_.x, origin_.y);
        vector<RTreeValue> initial_data;
        initial_data.emplace_back(rtree_points_.front(), 0);
        rtree_ = bgi::rtree<RTreeValue, bgi::quadratic<16>>(initial_data.begin(), initial_data.end());

        visualization_msgs::msg::Marker node_marker;
        visualization_msgs::msg::Marker line_marker;
        visualization_msgs::msg::Marker frontier_node_marker;
        visualization_msgs::msg::Marker sensing_circle_marker;
        visualization_msgs::msg::Marker exploration_circle_marker;
        node_marker.header.frame_id = LOCALIZATION_MAP;
        node_marker.header.stamp = node_->now();
        line_marker.header = node_marker.header;
        frontier_node_marker.header = node_marker.header;
        sensing_circle_marker.header = node_marker.header;
        exploration_circle_marker.header = node_marker.header;

        node_marker.ns = "ns_local_nodes";
        node_marker.action = visualization_msgs::msg::Marker::DELETEALL;
        node_marker.pose.orientation.w = 1.0;
        line_marker.ns = "ns_local_lines";
        line_marker.action = visualization_msgs::msg::Marker::DELETEALL;
        line_marker.pose.orientation.w = 1.0;
        frontier_node_marker.ns = "ns_local_frontier_nodes";
        frontier_node_marker.action = visualization_msgs::msg::Marker::DELETEALL;
        frontier_node_marker.pose.orientation.w = 1.0;
        sensing_circle_marker.ns = "ns_local_sensing_circle";
        sensing_circle_marker.action = visualization_msgs::msg::Marker::DELETEALL;
        sensing_circle_marker.pose.orientation.w = 1.0;
        exploration_circle_marker.ns = "ns_local_exploration_circle";
        exploration_circle_marker.action = visualization_msgs::msg::Marker::DELETEALL;
        exploration_circle_marker.pose.orientation.w = 1.0;

        rrt_node_marker_array_.markers.clear();
        rrt_line_marker_array_.markers.clear();
        rrt_frontier_node_marker_array_.markers.clear();
        rrt_sensing_circle_marker_array_.markers.clear();
        rrt_exploration_circle_marker_array_.markers.clear();

        rrt_node_marker_array_.markers.push_back(node_marker);
        rrt_line_marker_array_.markers.push_back(line_marker);
        rrt_frontier_node_marker_array_.markers.push_back(frontier_node_marker);
        rrt_sensing_circle_marker_array_.markers.push_back(sensing_circle_marker);
        rrt_exploration_circle_marker_array_.markers.push_back(exploration_circle_marker);

        rrt_node_marker_array_pub_->publish(rrt_node_marker_array_);
        rrt_line_marker_array_pub_->publish(rrt_line_marker_array_);
        rrt_frontier_node_marker_array_pub_->publish(rrt_frontier_node_marker_array_);
        rrt_sensing_circle_pub_->publish(rrt_sensing_circle_marker_array_);
        rrt_exploration_circle_pub_->publish(rrt_exploration_circle_marker_array_);

        rrt_node_marker_array_.markers.clear();
        rrt_line_marker_array_.markers.clear();
        rrt_frontier_node_marker_array_.markers.clear();
        rrt_sensing_circle_marker_array_.markers.clear();
        rrt_exploration_circle_marker_array_.markers.clear();

        try
        {
            tf_map_to_base_link_ = tf_buffer_->lookupTransform(
                LOCALIZATION_MAP,
                LOCALIZATION_BASE_LINK,
                tf2::TimePointZero, tf2::durationFromSec((float)timeout_secs));
        }
        catch (...)
        {
            cout << "no tf data from map to base_link." << endl;

            return frontier_points_;
        }

        try
        {
            auto grid = topic_utils::wait_for_message<nav_msgs::msg::OccupancyGrid>(
                node_.get(), "map", std::chrono::duration<double>((float)timeout_secs));

            if (grid != NULL)
            {
                map_data_ = *grid;
            }
        }
        catch (...)
        {
            cout << "could not get global map." << endl;

            return frontier_points_;
        }

        min_dist_to_obs_table_ = calc_min_dist_to_obs_table(map_data_, occupied_threshold_);

        origin_.x = tf_map_to_base_link_.transform.translation.x;
        origin_.y = tf_map_to_base_link_.transform.translation.y;
        origin_.z = tf_map_to_base_link_.transform.translation.z;

        rrt_tree_.indices.push_back(0);
        rrt_tree_.points.push_back(origin_);
        rrt_tree_.prev_indices.push_back(0);
        rrt_tree_.prev_points.push_back(origin_);
        rrt_tree_.next_indices.emplace_back();
        rrt_tree_.next_points.emplace_back();
        rrt_tree_.info_gains.push_back(0.0f);
        rrt_tree_.del_states.push_back(false);

        node_marker.header.stamp = node_->now();
        node_marker.id = rrt_tree_.indices[0];
        node_marker.type = visualization_msgs::msg::Marker::POINTS;
        node_marker.action = visualization_msgs::msg::Marker::ADD;
        node_marker.scale.x = 0.03;
        node_marker.scale.y = 0.03;
        node_marker.color.r = 0.0;
        node_marker.color.g = 0.0;
        node_marker.color.b = 1.0;
        node_marker.color.a = 1.0;

        geometry_msgs::msg::Point point;
        point.x = rrt_tree_.points[0].x;
        point.y = rrt_tree_.points[0].y;
        point.z = rrt_tree_.points[0].z;

        node_marker.points.clear();
        node_marker.points.push_back(point);

        rrt_node_marker_array_.markers.push_back(node_marker);

        rrt_node_marker_array_pub_->publish(rrt_node_marker_array_);

        rrt_node_marker_array_.markers.clear();

        sensing_circle_marker = generate_circle_msg(origin_.x, origin_.y, sensing_radius_,
                                                    0, "ns_local_sensing_circle",
                                                    0.0, 0.0, 1.0, 1.0);

        rrt_sensing_circle_marker_array_.markers.push_back(sensing_circle_marker);

        rrt_sensing_circle_pub_->publish(rrt_sensing_circle_marker_array_);

        rrt_sensing_circle_marker_array_.markers.clear();

        rclcpp::Time start_time = node_->now();

        vector<geometry_msgs::msg::Point32> current_downsampled_points;
        vector<geometry_msgs::msg::Point32> last_downsampled_points;
        size_t point_num_per_batch = static_cast<int>(((float)(pow(sensing_radius_, 2) * M_PI)) /
                                                      ((float)pow(rrt_coverage_check_density_, 2)));
        point_num_per_batch = point_num_per_batch < 2000 ? 2000 : point_num_per_batch;
        int sample_counter = point_num_per_batch;

        while ((node_->now() - start_time).seconds() <= timeout_secs)
        {
            sample_counter = point_num_per_batch;

            while (sample_counter--)
            {
                geometry_msgs::msg::Point32 sample_point;
                sample_point.x = (generate_random_number() * sensing_radius_ * 2.0f) - (sensing_radius_) + origin_.x;
                sample_point.y = (generate_random_number() * sensing_radius_ * 2.0f) - (sensing_radius_) + origin_.y;
                sample_point.z = 0;

                if (calculate_distance(origin_, sample_point) <= sensing_radius_)
                {
                    tuple<int, geometry_msgs::msg::Point32> nearest_point;

                    BGPoint query_pt(sample_point.x, sample_point.y);
                    vector<RTreeValue> result;
                    rtree_.query(bgi::nearest(query_pt, 1), back_inserter(result));
                    get<0>(nearest_point) = result.front().second;
                    get<1>(nearest_point) = rrt_tree_.points[get<0>(nearest_point)];

                    if (calculate_distance(get<1>(nearest_point), origin_) < 2 * min_dist_to_obs_ ||
                        !is_point_unknow(get<1>(nearest_point), map_data_, -1, -1))
                    {
                        float expand_dist = calc_decayed_distance(get<1>(nearest_point),
                                                                  map_data_, min_dist_to_obs_table_, min_dist_to_obs_,
                                                                  min_expand_dist_, max_expand_dist_);

                        geometry_msgs::msg::Point32 new_point = generate_point(get<1>(nearest_point), sample_point, expand_dist);

                        if (is_point_in_map(new_point, map_data_))
                        {
                            exploration_segment_type check_result;

                            if (get<0>(nearest_point) == 0 &&
                                calculate_distance(get<1>(nearest_point), new_point) <= min_dist_to_obs_)
                            {
                                check_result = exploration_check_segment_type(get<1>(nearest_point), new_point, 8,
                                                                              min_dist_to_obs_, map_data_, min_dist_to_obs_table_, false,
                                                                              free_threshold_, occupied_threshold_);
                            }
                            else
                            {
                                check_result = exploration_check_segment_type(get<1>(nearest_point), new_point, 8,
                                                                              min_dist_to_obs_, map_data_, min_dist_to_obs_table_, true,
                                                                              free_threshold_, occupied_threshold_);
                            }

                            if (check_result != exploration_segment_type::WITH_COLLISION)
                            {
                                rrt_tree_.indices.push_back(++node_index_);
                                rrt_tree_.points.push_back(new_point);
                                rrt_tree_.prev_indices.push_back(get<0>(nearest_point));
                                rrt_tree_.prev_points.push_back(get<1>(nearest_point));
                                rrt_tree_.next_indices.emplace_back();
                                rrt_tree_.next_points.emplace_back();
                                rrt_tree_.next_indices[get<0>(nearest_point)].push_back(node_index_);
                                rrt_tree_.next_points[get<0>(nearest_point)].push_back(new_point);
                                rrt_tree_.info_gains.push_back(0.0f);
                                rrt_tree_.del_states.push_back(false);

                                rtree_points_.emplace_back(new_point.x, new_point.y);
                                rtree_.insert(make_pair(rtree_points_.back(), node_index_));

                                node_marker.header.stamp = node_->now();
                                node_marker.id = node_index_;
                                node_marker.lifetime = rclcpp::Duration::from_seconds(0.2);
                                node_marker.type = visualization_msgs::msg::Marker::POINTS;
                                node_marker.action = visualization_msgs::msg::Marker::ADD;
                                node_marker.scale.x = 0.03;
                                node_marker.scale.y = 0.03;
                                node_marker.color.r = 0.0;
                                node_marker.color.g = 0.0;
                                node_marker.color.b = 1.0;
                                node_marker.color.a = 1.0;

                                geometry_msgs::msg::Point node_point;
                                node_point.x = new_point.x;
                                node_point.y = new_point.y;
                                node_point.z = new_point.z;

                                node_marker.points.clear();
                                node_marker.points.push_back(node_point);

                                rrt_node_marker_array_.markers.push_back(node_marker);

                                line_marker.header.stamp = node_->now();
                                line_marker.id = node_index_;
                                line_marker.lifetime = rclcpp::Duration::from_seconds(0.2);
                                line_marker.type = visualization_msgs::msg::Marker::LINE_STRIP;
                                line_marker.action = visualization_msgs::msg::Marker::ADD;
                                line_marker.scale.x = 0.02;
                                line_marker.color.r = 1.0;
                                line_marker.color.g = 0.0;
                                line_marker.color.b = 0.0;
                                line_marker.color.a = 1.0;

                                geometry_msgs::msg::Point start_point, end_point;
                                start_point.x = get<1>(nearest_point).x;
                                start_point.y = get<1>(nearest_point).y;
                                start_point.z = get<1>(nearest_point).z;
                                end_point.x = new_point.x;
                                end_point.y = new_point.y;
                                end_point.z = new_point.z;

                                line_marker.points.clear();
                                line_marker.points.push_back(start_point);
                                line_marker.points.push_back(end_point);

                                rrt_line_marker_array_.markers.push_back(line_marker);
                            }

                            if (check_result == exploration_segment_type::NO_COLLISION_WITH_UNKNOW)
                            {
                                frontier_points_.indices.push_back(node_index_);
                                frontier_points_.points.push_back(new_point);
                                frontier_points_.prev_indices.push_back(get<0>(nearest_point));
                                frontier_points_.prev_points.push_back(get<1>(nearest_point));
                                frontier_points_.next_indices.emplace_back();
                                frontier_points_.next_points.emplace_back();
                                frontier_points_.info_gains.push_back(0.0f);
                                frontier_points_.del_states.push_back(false);

                                auto resample_point_indices = resample_points(frontier_points_.points, frontier_points_.indices,
                                                                              frontier_points_min_dist_);

                                frontier_points_.indices.clear();
                                frontier_points_.points.clear();
                                frontier_points_.prev_indices.clear();
                                frontier_points_.prev_points.clear();
                                frontier_points_.next_indices.clear();
                                frontier_points_.next_points.clear();
                                frontier_points_.info_gains.clear();
                                frontier_points_.del_states.clear();

                                rrt_frontier_node_marker_array_.markers.clear();

                                frontier_node_marker.header.stamp = node_->now();
                                frontier_node_marker.action = visualization_msgs::msg::Marker::DELETEALL;
                                rrt_frontier_node_marker_array_.markers.push_back(frontier_node_marker);

                                rrt_frontier_node_marker_array_pub_->publish(rrt_frontier_node_marker_array_);

                                rrt_frontier_node_marker_array_.markers.clear();

                                size_t size = resample_point_indices.size();

                                for (int i = 0; i < size; i++)
                                {
                                    frontier_points_.indices.push_back(resample_point_indices[i]);
                                    frontier_points_.points.push_back(rrt_tree_.points[resample_point_indices[i]]);
                                    frontier_points_.prev_indices.push_back(rrt_tree_.prev_indices[resample_point_indices[i]]);
                                    frontier_points_.prev_points.push_back(rrt_tree_.points[rrt_tree_.prev_indices[resample_point_indices[i]]]);
                                    frontier_points_.next_indices.emplace_back();
                                    frontier_points_.next_points.emplace_back();
                                    frontier_points_.info_gains.push_back(calc_unknow_area(rrt_tree_.points[resample_point_indices[i]],
                                                                                           sensing_radius_, map_data_,
                                                                                           free_threshold_, occupied_threshold_));
                                    frontier_points_.del_states.push_back(false);
                                }

                                for (int i = 0; i < size; i++)
                                {
                                    frontier_node_marker.header.stamp = node_->now();
                                    frontier_node_marker.id = frontier_points_.indices[i];

                                    frontier_node_marker.type = visualization_msgs::msg::Marker::POINTS;
                                    frontier_node_marker.action = visualization_msgs::msg::Marker::ADD;
                                    frontier_node_marker.scale.x = 0.1;
                                    frontier_node_marker.scale.y = 0.1;
                                    frontier_node_marker.color.r = 1.0;
                                    frontier_node_marker.color.g = 1.0;
                                    frontier_node_marker.color.b = 0.0;
                                    frontier_node_marker.color.a = 1.0;

                                    geometry_msgs::msg::Point point;
                                    point.x = frontier_points_.points[i].x;
                                    point.y = frontier_points_.points[i].y;
                                    point.z = frontier_points_.points[i].z;

                                    frontier_node_marker.points.clear();
                                    frontier_node_marker.points.push_back(point);

                                    rrt_frontier_node_marker_array_.markers.push_back(frontier_node_marker);
                                }

                                rrt_frontier_node_marker_array_pub_->publish(rrt_frontier_node_marker_array_);

                                rrt_frontier_node_marker_array_.markers.clear();
                            }
                        }
                    }
                }
            }

            current_downsampled_points = resample_points(rrt_tree_.points, rrt_coverage_check_density_);

            if (current_downsampled_points.size() - last_downsampled_points.size() <= 2)
            {
                break;
            }

            last_downsampled_points = current_downsampled_points;
        }

        rrt_node_marker_array_pub_->publish(rrt_node_marker_array_);
        rrt_line_marker_array_pub_->publish(rrt_line_marker_array_);

        rrt_node_marker_array_.markers.clear();
        rrt_line_marker_array_.markers.clear();

        return frontier_points_;
    }

    visualization_msgs::msg::Marker local_explorer::generate_circle_msg(const float &x, const float &y, const float &radius,
                                                                   const int &index, const string &ns,
                                                                   const float &r, const float &g, const float &b, const float &a)
    {
        visualization_msgs::msg::Marker marker;

        marker.header.frame_id = LOCALIZATION_MAP;
        marker.header.stamp = node_->now();
        marker.ns = ns;
        marker.id = index;
        marker.type = visualization_msgs::msg::Marker::LINE_STRIP;
        marker.action = visualization_msgs::msg::Marker::ADD;

        marker.scale.x = 0.02;
        marker.color.r = r;
        marker.color.g = g;
        marker.color.b = b;
        marker.color.a = a;
        marker.pose.orientation.w = 1.0;

        const int num_points = 20;

        for (int i = 0; i <= num_points; ++i)
        {
            float theta = 2.0 * M_PI * i / num_points;

            geometry_msgs::msg::Point p;
            p.x = x + radius * std::cos(theta);
            p.y = y + radius * std::sin(theta);
            p.z = 0;

            marker.points.push_back(p);
        }

        return marker;
    }

    float local_explorer::generate_random_number()
    {
        return (*gen_random_number_)(*random_generator_);
    }
}