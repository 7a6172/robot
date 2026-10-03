#ifndef MATH_UTILS
#define MATH_UTILS

#include <rclcpp/rclcpp.hpp>
#include <tf2/utils.hpp>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>
#include <geometry_msgs/msg/polygon.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <angles/angles.h>
#include <openmover_msgs/msg/obstacle.hpp>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <opencv2/opencv.hpp>
#include <opencv2/imgproc/imgproc.hpp>
#include <octomap/octomap.h>
#include <tuple>
#include <pcl/point_cloud.h>
#include <pcl/point_types.h>
#include <boost/uuid/uuid.hpp>
#include <boost/uuid/uuid_generators.hpp>
#include <boost/uuid/uuid_io.hpp>
#include <pcl/kdtree/kdtree_flann.h>
#include <pcl/filters/voxel_grid.h>
#include <omp.h>

using namespace std;

enum obstacle_line_type
{
    FRONT = 0,
    REAR = 1,
    LEFT = 2,
    RIGHT = 3
};

struct obstacle_line
{
    obstacle_line_type type;
    geometry_msgs::msg::Point32 p0;
    geometry_msgs::msg::Point32 p1;
};

enum obstacle_type
{
    CONVEX = 0,
    CIRCLE = 1
};

extern boost::uuids::random_generator uuid_generator;

struct obstacle_description
{
    string uuid;
    obstacle_type type;
    float radius;
    geometry_msgs::msg::Point32 center;
    vector<obstacle_line> boundaries;
    obstacle_line center_line;
};

geometry_msgs::msg::Polygon transform_footprint(geometry_msgs::msg::PoseWithCovarianceStamped &pose,
                                           geometry_msgs::msg::Polygon &footprint);

tuple<vector<obstacle_line>, vector<float>> create_obstacle_lines(geometry_msgs::msg::PoseWithCovarianceStamped &pose,
                                                                  geometry_msgs::msg::Polygon &footprint,
                                                                  openmover_msgs::msg::Obstacle &obstacle);

int orientation(const geometry_msgs::msg::Point32 &p, const geometry_msgs::msg::Point32 &q, const geometry_msgs::msg::Point32 &r);

bool on_segment(const geometry_msgs::msg::Point32 &p, const geometry_msgs::msg::Point32 &q, const geometry_msgs::msg::Point32 &r);

bool is_intersect(const geometry_msgs::msg::Point32 &p1,
                  const geometry_msgs::msg::Point32 &p2,
                  const geometry_msgs::msg::Point32 &p3,
                  const geometry_msgs::msg::Point32 &p4);

bool is_point_in_rect(const geometry_msgs::msg::Point32 &p, const geometry_msgs::msg::Polygon &rect);

bool is_point_in_obstacle(const geometry_msgs::msg::Point32 &p, const obstacle_description &ob);

bool is_line_intersect_rect(geometry_msgs::msg::Polygon &polygon, vector<obstacle_line> &lines);

bool is_rect_intersect(const obstacle_description &rect1, const obstacle_description &rect2);

bool is_obstacle_intersect(const obstacle_description &ob1, const obstacle_description &ob2);

bool is_obstacle_in_obstacle(const obstacle_description &ob1, const obstacle_description &ob2);

bool is_obstacle_almost_in_obstacle(const obstacle_description &ob1, const obstacle_description &ob2);

float calc_path_point_orientation(geometry_msgs::msg::Pose &pose, vector<geometry_msgs::msg::Pose> &forward_points);

obstacle_description circle_to_convex(float cx, float cy, float r, int subdivisions = 12);

bool is_footprint_has_occupied_point(nav_msgs::msg::OccupancyGrid::ConstSharedPtr grid,
                                     geometry_msgs::msg::Polygon &footprint,
                                     const geometry_msgs::msg::PoseStamped &pose,
                                     float stop_distance,
                                     bool reversed = false,
                                     int sampling_ratio = 1,
                                     float padding_ratio = 1.2);

geometry_msgs::msg::Point32 calculate_polygon_center(const geometry_msgs::msg::Polygon &polygon);

geometry_msgs::msg::Point32 calculate_line_center(const obstacle_line &line);

float calculate_distance(const geometry_msgs::msg::Point32 &p1, const geometry_msgs::msg::Point32 &p2);

float calculate_distance(const geometry_msgs::msg::Pose &p1, const geometry_msgs::msg::Pose &p2);

float calculate_distance(const octomap::point3d &p1, const octomap::point3d &p2);

float calculate_distance(const cv::Point2f &p1, const cv::Point2f &p2);

float calculate_distance(const pcl::PointXY &p1, const pcl::PointXY &p2);

float calculate_distance(const pcl::PointXYZ &p1, const pcl::PointXYZ &p2);

geometry_msgs::msg::Point32 create_point(const float &x, const float &y);

geometry_msgs::msg::Point32 create_point(const float &x, const float &y, const float &z);

geometry_msgs::msg::Point create_pointd(const float &x, const float &y);

geometry_msgs::msg::Point create_pointd(const float &x, const float &y, const float &z);

geometry_msgs::msg::Point point_ros_to_rosd(const geometry_msgs::msg::Point32 &p);

octomap::point3d point_ros_to_octomap(const geometry_msgs::msg::Point32 &p);

geometry_msgs::msg::Point32 point_octomap_to_ros(const octomap::point3d &p);

cv::Point2f point_ros_to_cv(const geometry_msgs::msg::Point32 &p);

geometry_msgs::msg::Point32 point_cv_to_ros(const cv::Point2f &p);

geometry_msgs::msg::Point point_cv_to_rosd(const cv::Point2f &p);

geometry_msgs::msg::Point32 point_pcl_xyz_to_ros(const pcl::PointXYZ &p);

pcl::PointXYZRGB point_ros_to_pcl_xyzrgb(const geometry_msgs::msg::Point32 &p);

geometry_msgs::msg::Point32 point_pcl_xyzrgb_to_ros(const pcl::PointXYZRGB &p);

geometry_msgs::msg::Point point_pcl_xyz_to_rosd(const pcl::PointXYZ &p);

geometry_msgs::msg::Point point_pcl_xyzrgb_to_rosd(const pcl::PointXYZRGB &p);

geometry_msgs::msg::Polygon points_to_polygon(const vector<geometry_msgs::msg::Point32> &points);

geometry_msgs::msg::Polygon points_to_polygon(const vector<octomap::point3d> &points);

geometry_msgs::msg::Polygon points_to_polygon(const vector<cv::Point2f> &points);

geometry_msgs::msg::Polygon points_to_polygon(const geometry_msgs::msg::Point32 &p0,
                                         const geometry_msgs::msg::Point32 &p1,
                                         const geometry_msgs::msg::Point32 &p2,
                                         const geometry_msgs::msg::Point32 &p3);

geometry_msgs::msg::Polygon points_to_polygon(const octomap::point3d &p0,
                                         const octomap::point3d &p1,
                                         const octomap::point3d &p2,
                                         const octomap::point3d &p3);

geometry_msgs::msg::Polygon points_to_polygon(const cv::Point2f &p0,
                                         const cv::Point2f &p1,
                                         const cv::Point2f &p2,
                                         const cv::Point2f &p3);

tuple<geometry_msgs::msg::Point32, geometry_msgs::msg::Point32> get_box_aabb(const geometry_msgs::msg::Polygon &polygon);

tuple<geometry_msgs::msg::Point32, geometry_msgs::msg::Point32> get_box_aabb(const obstacle_description &obstacle);

tuple<int, int, int, int> get_box_aabb_in_grid(const geometry_msgs::msg::Polygon &polygon,
                                               const nav_msgs::msg::OccupancyGrid &grid);

tuple<int, int, int, int> get_box_aabb_in_grid(const obstacle_description &obstacle,
                                               const nav_msgs::msg::OccupancyGrid &grid);

geometry_msgs::msg::Point32 grid_xy_to_position(const int &x, const int &y, const nav_msgs::msg::OccupancyGrid &grid);

geometry_msgs::msg::Point32 grid_index_to_position(const int &index, const nav_msgs::msg::OccupancyGrid &grid);

pcl::PointXYZ grid_xy_to_pointcloud_xyz(const int &x, const int &y, const nav_msgs::msg::OccupancyGrid &grid);

pcl::PointXYZ grid_index_to_pointcloud_xyz(const int &index, const nav_msgs::msg::OccupancyGrid &grid);

pcl::PointXYZRGB grid_xy_to_pointcloud_xyzrgb(const int &x, const int &y, const nav_msgs::msg::OccupancyGrid &grid);

pcl::PointXYZRGB grid_index_to_pointcloud_xyzrgb(const int &index, const nav_msgs::msg::OccupancyGrid &grid);

geometry_msgs::msg::Point32 grid_index_to_position(const int &index, const nav_msgs::msg::OccupancyGrid &grid);

int grid_xy_to_grid_index(const int &x, const int &y, const nav_msgs::msg::OccupancyGrid &grid);

tuple<int, int> grid_index_to_grid_xy(const int &index, const nav_msgs::msg::OccupancyGrid &grid);

tuple<int, int> position_to_grid_xy(const geometry_msgs::msg::Point32 &p, const nav_msgs::msg::OccupancyGrid &grid);

tuple<int, int> position_to_grid_xy(const octomap::point3d &p, const nav_msgs::msg::OccupancyGrid &grid);

tuple<int, int> position_to_grid_xy(const cv::Point2f &p, const nav_msgs::msg::OccupancyGrid &grid);

tuple<int, int> position_to_grid_xy(const pcl::PointXYZ &p, const nav_msgs::msg::OccupancyGrid &grid);

tuple<int, int> position_to_grid_xy(const pcl::PointXYZRGB &p, const nav_msgs::msg::OccupancyGrid &grid);

int position_to_grid_index(const geometry_msgs::msg::Point32 &p, const nav_msgs::msg::OccupancyGrid &grid);

int position_to_grid_index(const octomap::point3d &p, const nav_msgs::msg::OccupancyGrid &grid);

int position_to_grid_index(const cv::Point2f &p, const nav_msgs::msg::OccupancyGrid &grid);

obstacle_line create_line(const geometry_msgs::msg::Point32 &p0, const geometry_msgs::msg::Point32 &p1);

obstacle_line create_line(const float &x0, const float &y0, const float &x1, const float &y1);

obstacle_line create_line(const geometry_msgs::msg::Point &p0, const geometry_msgs::msg::Point &p1);

obstacle_description create_obstacle(const geometry_msgs::msg::Point32 &pos, const float &radius);

obstacle_description create_obstacle(const vector<obstacle_line> &boundaries);

float min_distance_to_line(const geometry_msgs::msg::Point32 &p, const obstacle_line &line);

bool is_line_in_or_cross_circle(const geometry_msgs::msg::Point32 &pos, const float &radius, const obstacle_line &line);

bool is_obstacle_in_roi(const geometry_msgs::msg::Point32 &pos, const float &radius, const obstacle_description &obstacle);

vector<obstacle_description> get_obstacles_in_roi(const geometry_msgs::msg::Point32 &pos, const float &radius, const vector<obstacle_description> &obstacles);

bool is_point_in_circle(const geometry_msgs::msg::Point32 &center, const float &radius, const geometry_msgs::msg::Point32 &p);

tuple<geometry_msgs::msg::Point32, float> circle_from_two_points(const geometry_msgs::msg::Point32 &p1, const geometry_msgs::msg::Point32 &p2);

tuple<geometry_msgs::msg::Point32, float> circle_from_three_points(const geometry_msgs::msg::Point32 &p1, const geometry_msgs::msg::Point32 &p2, const geometry_msgs::msg::Point32 &p3);

tuple<geometry_msgs::msg::Point32, float> welzl(vector<geometry_msgs::msg::Point32> points, vector<geometry_msgs::msg::Point32> points_recurs, size_t n);

tuple<geometry_msgs::msg::Point32, float> find_min_bounding_circle(const vector<geometry_msgs::msg::Point32> &points);

tuple<geometry_msgs::msg::Point32, float> find_min_bounding_circle(const pcl::PointCloud<pcl::PointXYZ> &points);

tuple<geometry_msgs::msg::Point32, float> find_min_bounding_circle(const pcl::PointCloud<pcl::PointXYZRGB> &points);

float min_dist_between_obstacles(const obstacle_description &ob1, const obstacle_description &ob2);

vector<geometry_msgs::msg::PoseStamped> calc_path_orientation(const vector<geometry_msgs::msg::PoseStamped> &path);

vector<int> enumerate_line_indices(const float &x0, const float &y0, const float &x1, const float &y1,
                                   const int &width, const int &height, const float &resolu);

vector<int> enumerate_line_indices(const geometry_msgs::msg::Point32 &p0, const geometry_msgs::msg::Point32 &p1,
                                   const nav_msgs::msg::OccupancyGrid &grid);

bool is_segment_no_collision(const float &x0, const float &y0, const float &x1, const float &y1, const int &step,
                             const int &width, const int &height, const float &resolu,
                             const float &min_obs_dist,
                             const vector<float> &obs_dist_table);

enum exploration_segment_type
{
    NO_COLLISION_WITH_UNKNOW = -1,
    NO_COLLISION = 0,
    WITH_COLLISION = 1
};

exploration_segment_type exploration_check_segment_type(const geometry_msgs::msg::Point32 &p0, const geometry_msgs::msg::Point32 &p1, const int &step,
                                                        const float &min_obs_dist,
                                                        const nav_msgs::msg::OccupancyGrid &grid,
                                                        const vector<float> &obs_dist_table,
                                                        const bool &check_obs,
                                                        const int &free_threshold = 30, const int &occupied_threshold = 60);

nav_msgs::msg::OccupancyGrid clear_footprint_on_grid(const nav_msgs::msg::OccupancyGrid &grid,
                                                const geometry_msgs::msg::Point32 &origin, const float &radius);

vector<float> calc_min_dist_to_obs_table(const nav_msgs::msg::OccupancyGrid &grid, const int &threshold);

vector<float> calc_min_dist_to_obs_table(const nav_msgs::msg::OccupancyGrid &grid,
                                         const float center_x, const float center_y, const float radius,
                                         const int &threshold);

vector<int> resample_points(const vector<geometry_msgs::msg::Point32> &points, const vector<int> &indices,
                            const float &min_dist);

vector<geometry_msgs::msg::Point32> resample_points(const vector<geometry_msgs::msg::Point32> &points, const float &min_dist);

geometry_msgs::msg::Point32 generate_point(const geometry_msgs::msg::Point32 &p0, const geometry_msgs::msg::Point32 &dir, const float &dist);

geometry_msgs::msg::Point32 generate_point_on_segment(const geometry_msgs::msg::Point32 &p0, const geometry_msgs::msg::Point32 &dir, const float &dist);

float calc_unknow_area(const geometry_msgs::msg::Point32 &p, const float &radius, const nav_msgs::msg::OccupancyGrid &grid,
                       const int &free_threshold = 30, const int &occupied_threshold = 60);

tuple<int, geometry_msgs::msg::Point32> get_nearest_point(const geometry_msgs::msg::Point32 &p,
                                                     const vector<geometry_msgs::msg::Point32> &points, const vector<int> &indices);

tuple<int, geometry_msgs::msg::Point32> get_nearest_point(const geometry_msgs::msg::Point32 &p,
                                                     const vector<geometry_msgs::msg::Point32> &points, const vector<int> &indices, const vector<bool> &del_states);

bool is_point_in_map(const geometry_msgs::msg::Point32 &p, const nav_msgs::msg::OccupancyGrid &grid);

bool is_point_unknow(const geometry_msgs::msg::Point32 &p, const nav_msgs::msg::OccupancyGrid &grid,
                     const int &free_threshold = 30, const int &occupied_threshold = 60);

float calc_decayed_distance(const geometry_msgs::msg::Point32 &p, const nav_msgs::msg::OccupancyGrid &grid, const vector<float> &obs_dist_table,
                            const float &min_dist_to_obs, const float &min_expand_dist, const float &max_expand_dist);

float calc_orientation_diff(const geometry_msgs::msg::Point32 &p0, const geometry_msgs::msg::Point32 &p1, const geometry_msgs::msg::Point32 &p2);

float calc_coverage_rate(const vector<geometry_msgs::msg::Point32> &points, const float &sensing_radius);

float calc_coverage_density(const vector<geometry_msgs::msg::Point32> &points, const vector<geometry_msgs::msg::Point32> &prev_points);

tuple<float, float> get_grid_max_min(const nav_msgs::msg::OccupancyGrid &grid);

vector<geometry_msgs::msg::Point32> get_round_points(const geometry_msgs::msg::Point32 &p,
                                                const float &radius, const int &num,
                                                const nav_msgs::msg::OccupancyGrid &grid,
                                                const float &min_obs_dist, const vector<float> &obs_dist_table);

vector<geometry_msgs::msg::PoseStamped> get_round_points(const geometry_msgs::msg::PoseStamped &p,
                                                    const float &radius, const int &num,
                                                    const nav_msgs::msg::OccupancyGrid &grid,
                                                    const float &min_obs_dist, const vector<float> &obs_dist_table);

float calc_seg_direction(const geometry_msgs::msg::PoseStamped &p0, const geometry_msgs::msg::Point32 &p1);

float calc_map_area(const nav_msgs::msg::OccupancyGrid &grid,
                    const int &free_threshold = 30, const int &occupied_threshold = 60);

// tf::createQuaternionMsgFromYaw 的 ROS 2 等价实现
static inline geometry_msgs::msg::Quaternion quaternion_msg_from_yaw(double yaw)
{
    tf2::Quaternion q;
    q.setRPY(0.0, 0.0, yaw);
    return tf2::toMsg(q);
}

#endif
