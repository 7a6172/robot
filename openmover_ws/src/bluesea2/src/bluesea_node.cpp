/*********************************************************************
 * Lanhai ROS 2 driver (ported from the ROS 1 bluesea2 driver)
 *
 * ROS 2 adaptations:
 *  - all parameters are declared on a single node (ROS 2 has no
 *    private/global namespaces); names and defaults are unchanged;
 *  - motor control services are advertised relative to the node name
 *    (e.g. /bluesea2_node/stop_motor) so several lidar nodes can coexist;
 *  - point cloud output uses sensor_msgs/msg/PointCloud2
 *    (sensor_msgs/PointCloud was dropped in ROS 2);
 *  - optional custom angle masks must be passed as mask1..mask8.
 *********************************************************************/

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/laser_scan.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <sensor_msgs/msg/point_field.hpp>

#include <bluesea2/srv/control.hpp>
#include <bluesea2/srv/defence_zone.hpp>

#include <time.h>
#include <sys/stat.h>
#include <pthread.h>
#include <signal.h>
#include <unistd.h>

#include "reader.h"
#include "data_process.h"
#include "algorithmAPI.h"

static rclcpp::Node::SharedPtr g_node;
static rclcpp::Clock::SharedPtr g_clock;

HReader g_reader = NULL;
std::string g_type = "uart";
bool g_should_start = true;
#define BLUESEA2_VERSION "2.0.0"

struct Range
{
	double min;
	double max;
};

struct PubHub
{
	pthread_mutex_t mtx;
	int nfan;
	RawData *fans[MAX_FANS];
	int error_num;
	int offsetangle;
};

void closeSignal(int sig)
{
	(void)sig;
	printf("shutting down!\n");
	rclcpp::shutdown();
	exit(1);
}

void SetTimeStamp(RawData *dat)
{
	if (g_clock == nullptr)
		return;
	auto t = g_clock->now();
	dat->ts[0] = (uint32_t)t.seconds();
	dat->ts[1] = (uint32_t)(t.nanoseconds() % 1000000000LL);
}

bool SendCmd(int len, char *cmd, int index)
{
	if (g_type == "uart")
	{
		return SendUartCmd(g_reader, len, cmd);
	}
	else if (g_type == "vpc")
	{
		return SendVpcCmd(g_reader, len, cmd);
	}
	else if (g_type == "udp")
	{
		if (index < 0)
		{
			int tmp = 0;
			memcpy(&tmp, g_reader, sizeof(int));
			for (int i = 0; i < tmp; i++)
			{
				SendUdpCmd(g_reader, i, len, cmd);
			}
			return true;
		}
		else
			return SendUdpCmd(g_reader, index, len, cmd);
	}
	else if (g_type == "tcp")
	{
		return SendTcpCmd(g_reader, len, cmd);
	}
	return false;
}

void PublishData(HPublish pub, int n, RawData **fans)
{
	int skip = 0;
	RawData *drop[MAX_FANS];
	PubHub *hub = (PubHub *)pub;

	pthread_mutex_lock(&hub->mtx);

	if (hub->nfan + n > MAX_FANS)
	{
		int nr = hub->nfan + n - MAX_FANS;

		for (int i = 0; i < nr; i++)
			drop[skip++] = hub->fans[i];

		for (int i = nr; i < hub->nfan; i++)
		{
			hub->fans[i - nr] = hub->fans[i];
		}

		hub->nfan -= nr;
	}

	for (int i = 0; i < n; i++)
	{
		hub->fans[hub->nfan++] = fans[i];
	}

	pthread_mutex_unlock(&hub->mtx);

	for (int i = 0; i < skip; i++)
	{
		delete drop[i];
	}
}

void resample(RawData *dat, int NN)
{
	int *index = new int[NN];
	double *errs = new double[NN];

	for (int i = 0; i < NN; i++)
		index[i] = -1;

	for (int i = 0; i < dat->N; i++)
	{
		if (dat->points[i].distance == 0)
			continue;

		int idx = round(double(i * NN) / dat->N);
		if (idx < NN)
		{
			double err = fabs(double(dat->span * i) / dat->N - double(dat->span * idx) / NN);
			if (index[idx] == -1 || err < errs[idx])
			{
				index[idx] = i;
				errs[idx] = err;
			}
		}
	}

	for (int i = 1; i < NN; i++)
	{
		if (index[i] != -1)
		{
			dat->points[i] = dat->points[index[i]];
		}
		else
		{
			dat->points[i].distance = 0;
			dat->points[i].confidence = 0;
		}
		dat->points[i].degree = dat->angle / 10.0 + (dat->span * i) / (10.0 * NN);
	}

	dat->N = NN;

	delete[] index;
	delete[] errs;
}

bool GetFan(HPublish pub, bool with_resample, double resample_res, RawData **fans)
{
	bool got = false;
	PubHub *hub = (PubHub *)pub;
	if (hub->nfan > 0)
	{
		pthread_mutex_lock(&hub->mtx);
		fans[0] = hub->fans[0];
		for (int i = 1; i < hub->nfan; i++)
			hub->fans[i - 1] = hub->fans[i];
		hub->nfan--;
		got = true;
		pthread_mutex_unlock(&hub->mtx);
	}
	else
		return false;

	if (with_resample)
	{
		int NN = fans[0]->span / (10 * resample_res);

		if (NN < fans[0]->N)
		{
			resample(fans[0], NN);
		}
		else if (NN > fans[0]->N)
		{
			printf("fan %d less than %d\n", fans[0]->N, NN);
		}
	}
	return got;
}

int GetAllFans(HPublish pub, bool with_resample, double resample_res, RawData **fans, int collect_angle,
			   uint32_t *ts_beg, uint32_t *ts_end, int error_circle, double error_scale)
{
	PubHub *hub = (PubHub *)pub;
	pthread_mutex_lock(&hub->mtx);

	int cnt = 0;

	for (int i = 1; i < hub->nfan; i++)
	{
		if (hub->fans[i]->angle == hub->offsetangle * 10)
		{
			ts_end[0] = hub->fans[i]->ts[0];
			ts_end[1] = hub->fans[i]->ts[1];

			cnt = i;
			break;
		}
	}

	if (cnt > 0)
	{
		for (int i = 0; i < cnt; i++)
		{
			fans[i] = hub->fans[i];
		}
		for (int i = cnt; i < hub->nfan; i++)
			hub->fans[i - cnt] = hub->fans[i];
		hub->nfan -= cnt;
	}
	pthread_mutex_unlock(&hub->mtx);

	if (cnt > 0)
	{
		bool circle = true;
		int total = fans[0]->span;
		ts_beg[0] = fans[0]->ts[0];
		ts_beg[1] = fans[0]->ts[1];

		for (int i = 0; i < cnt - 1; i++)
		{
			if ((fans[i]->angle + fans[i]->span) % 3600 != fans[i + 1]->angle)
			{
				circle = false;
			}
			total += fans[i + 1]->span;
		}
		if (!circle || total != 3600)
		{
			printf("%d drop %d fans \n", total, cnt);
			for (int i = 0; i < cnt; i++)
				delete fans[i];
			cnt = 0;
		}
		int sum = 0;
		int lengthZeroNum = 0;
		for (int i = 0; i < cnt; i++)
		{
			sum += fans[i]->N;
			for (int j = 0; j < fans[i]->N; j++)
			{
				if (fans[i]->points[j].distance == 0)
				{
					lengthZeroNum++;
				}
			}
		}
		if (sum * error_scale < lengthZeroNum)
			hub->error_num++;

		if (hub->error_num >= error_circle)
		{
			printf("There are many points with a distance of 0 in the current lidar operation,sum:%d lengthZeroNum:%d\n", sum, lengthZeroNum);
			hub->error_num = 0;
		}
	}
	if (cnt > 0)
	{
		if (with_resample && resample_res > 0)
		{
			for (int i = 0; i < cnt; i++)
			{
				int NN = fans[i]->span / (10 * resample_res);
				if (NN < fans[i]->N)
				{
					resample(fans[i], NN);
				}
				else if (NN > fans[i]->N)
				{
					printf("fan [%d] %d less than %d\n", i, fans[i]->N, NN);
				}
			}
		}
	}
	return cnt;
}

double ROSAng(double ang)
{
	ang = -ang;
	return ang < -180 ? ang + 360 : ang;
}

int GetCount(int nfan, RawData **fans, double min_deg, double max_deg, double &min_pos, double &max_pos)
{
	int N = 0, cnt = 0;

	for (int j = 0; j < nfan; j++)
	{
		for (int i = fans[j]->N - 1; i >= 0; i--, cnt++)
		{
			double deg = ROSAng(fans[j]->points[i].degree);

			if (deg < min_deg || deg > max_deg)
				continue;
			if (N == 0)
			{
				min_pos = deg;
				max_pos = deg;
			}
			else
			{
				if (min_pos > deg)
					min_pos = deg;
				if (max_pos < deg)
					max_pos = deg;
			}
			N++;
		}
	}
	return N;
}

void getMSGData(sensor_msgs::msg::LaserScan &msg, RawData *fan, bool reversed,
				double min_ang, double max_ang, double min_dist, double max_dist, bool with_filter, const std::vector<Range> &custom_masks, int i, int index)
{
	int start, end;
	if (i == -1)
	{
		start = 0;
		end = fan->N;
	}
	else if (i == 0)
	{
		if (reversed)
		{
			start = index;
			end = fan->N;
		}
		else
		{
			start = 0;
			end = index;
		}
	}
	else if (i == 1)
	{
		if (reversed)
		{
			start = 0;
			end = index;
		}
		else
		{
			start = index;
			end = fan->N;
		}
	}
	int N = 0;
	double min_deg = min_ang * 180 / M_PI;
	double max_deg = max_ang * 180 / M_PI;
	if (reversed)
	{
		for (int i = end - 1; i >= start; i--)
		{
			double deg = ROSAng(fan->points[i].degree);
			if (with_filter)
			{
				if (deg < min_deg)
					continue;
				if (deg > max_deg)
					continue;
			}

			// customize angle filter
			bool custom = false;
			for (unsigned int k = 0; k < custom_masks.size() && !custom; k++)
			{
				if (with_filter && custom_masks[k].min < deg && deg < custom_masks[k].max)
					custom = true;
			}

			double d = fan->points[i].distance / 1000.0;

			if (fan->points[i].distance == 0 || d > max_dist || d < min_dist || custom)
				msg.ranges[N] = std::numeric_limits<float>::infinity();
			else
				msg.ranges[N] = d;

			msg.intensities[N] = fan->points[i].confidence;
			N++;
		}
	}
	else
	{
		for (int i = start; i < end; i++)
		{
			double deg = ROSAng(fan->points[i].degree);
			if (with_filter)
			{
				if (deg < min_deg)
					continue;
				if (deg > max_deg)
					continue;
			}

			// customize angle filter
			bool custom = false;
			for (unsigned int k = 0; k < custom_masks.size() && !custom; k++)
			{
				if (with_filter && custom_masks[k].min < deg && deg < custom_masks[k].max)
					custom = true;
			}

			double d = fan->points[i].distance / 1000.0;

			if (fan->points[i].distance == 0 || d > max_dist || d < min_dist || custom)
				msg.ranges[N] = std::numeric_limits<float>::infinity();
			else
				msg.ranges[N] = d;

			msg.intensities[N] = fan->points[i].confidence;
			N++;
		}
	}
}

void PublishLaserScanFan(rclcpp::Publisher<sensor_msgs::msg::LaserScan>::SharedPtr laser_pub, RawData *fan,
						 std::string &frame_id,
						 double min_dist, double max_dist,
						 bool with_filter, double min_ang, double max_ang,
						 bool inverted, bool reversed, double zero_shift, bool from_zero,
						 const std::vector<Range> &custom_masks, int collect_angle)
{
	int N = fan->N;

	if (zero_shift > M_PI || zero_shift < -M_PI)
	{
		int num = zero_shift / M_PI;
		zero_shift = zero_shift - num * M_PI;
	}
	if (zero_shift != 0)
	{
		double zero_shift_tmp = zero_shift * 180 / M_PI;
		for (int i = 0; i < N; i++)
		{
			double deg = fan->points[i].degree + zero_shift_tmp;
			fan->points[i].degree = deg;
		}
	}
	bool isspecial = false;
	int index = 0;
	int tmp_angle = from_zero ? 0 : 1800;
	if (from_zero)
	{
		if (fan->angle < 3600 && (fan->angle + fan->span) > 3600)
		{
			index = (3600 - fan->angle) * 1.0 / fan->span * fan->N;
			isspecial = true;
		}
		else
			index = -1;
	}
	else
	{
		if (fan->angle < 1800 && (fan->angle + fan->span) > 1800)
		{
			index = (1800 - fan->angle) * 1.0 / fan->span * fan->N;
			isspecial = true;
		}
		else
			index = -1;
	}
	RawData tmpdata[2];
	tmpdata[0].angle = fan->angle;
	tmpdata[0].span = fan->span * index / fan->N;
	tmpdata[0].N = index;

	tmpdata[1].angle = tmp_angle;
	tmpdata[1].span = fan->span * (fan->N - index) / fan->N;
	tmpdata[1].N = fan->N - index;

	sensor_msgs::msg::LaserScan msg;
	msg.header.stamp.sec = fan->ts[0];
	msg.header.stamp.nanosec = fan->ts[1];

	msg.header.frame_id = frame_id;

	double scan_time = 1 / 100.;
	msg.scan_time = scan_time;
	msg.time_increment = scan_time / fan->N;

	msg.range_min = min_dist;
	msg.range_max = max_dist;
	double min_pos, max_pos;
	if (1)
	{
		if (inverted)
		{
			min_pos = ROSAng(-fan->angle / 10) * 10 * M_PI / 1800;
			max_pos = -min_pos;
		}
		else
		{
			min_pos = ROSAng(fan->angle / 10) * 10 * M_PI / 1800;
			max_pos = min_pos;
		}
		msg.intensities.resize(N);
		msg.ranges.resize(N);

		if (inverted)
		{
			msg.angle_min = min_pos;
			msg.angle_max = max_pos;
			msg.angle_increment = (fan->span * M_PI / 1800) / fan->N;
		}
		else
		{
			msg.angle_min = max_pos;
			msg.angle_max = min_pos;
			msg.angle_increment = -(fan->span * M_PI / 1800) / fan->N;
		}
		getMSGData(msg, fan, reversed, min_ang, max_ang, min_dist, max_dist, with_filter, custom_masks, -1, index);
		laser_pub->publish(msg);
		return;
	}
	else
	{
		for (int i = 0; i < 2; i++)
		{
			msg.intensities.resize(tmpdata[i].N);
			msg.ranges.resize(tmpdata[i].N);
			double min_pos, max_pos;

			if (inverted)
			{
				min_pos = ROSAng(-tmpdata[i].angle / 10) * 10 * M_PI / 1800;
				max_pos = -min_pos + tmpdata[i].span * M_PI / 1800;
				msg.angle_min = min_pos;
				msg.angle_max = max_pos;
				msg.angle_increment = (fan->span * M_PI / 1800) / fan->N;
			}
			else
			{
				min_pos = ROSAng(tmpdata[i].angle / 10) * 10 * M_PI / 1800;
				max_pos = min_pos - tmpdata[i].span * M_PI / 1800;
				msg.angle_min = max_pos;
				msg.angle_max = min_pos;
				msg.angle_increment = -(fan->span * M_PI / 1800) / fan->N;
			}
			getMSGData(msg, fan, reversed, min_ang, max_ang, min_dist, max_dist, with_filter, custom_masks, i, index);
			laser_pub->publish(msg);
		}
	}
}

int time_cmp(const uint32_t *t1, const uint32_t *t2)
{
	if (t1[0] > t2[0])
		return 1;
	else if (t1[0] < t2[0])
		return -1;
	else if (t1[1] > t2[1])
		return 1;
	else if (t1[1] < t2[1])
		return -1;

	return 0;
}

uint32_t last_ns = 0;

void PublishLaserScan(rclcpp::Publisher<sensor_msgs::msg::LaserScan>::SharedPtr laser_pub, int nfan, RawData **fans, std::string &frame_id,
					  double min_dist, double max_dist, bool with_filter, double min_ang, double max_ang,
					  bool inverted, bool reversed, double zero_shift,
					  bool from_zero, uint32_t *ts_beg, uint32_t *ts_end,
					  const std::vector<Range> &custom_masks, int collect_angle,
					  bool filter_open, int filter_type, float max_range, float min_range, double max_range_difference, int filter_window)
{
	sensor_msgs::msg::LaserScan msg, filtered_scan;
	int N = 0;
	if (zero_shift > M_PI || zero_shift < -M_PI)
	{
		int num = zero_shift / M_PI;
		zero_shift = zero_shift - num * M_PI;
	}

	double zero_shift_tmp = zero_shift * 180 / M_PI;
	for (int j = 0; j < nfan; j++)
	{
		N += fans[j]->N;
		if (zero_shift == 0)
			continue;
		for (int i = 0; i < fans[j]->N; i++)
		{
			double deg = fans[j]->points[i].degree + zero_shift_tmp;
			fans[j]->points[i].degree = deg;
		}
	}

	msg.header.stamp.sec = ts_beg[0];
	msg.header.stamp.nanosec = ts_beg[1];

	double ti = double(ts_beg[0]) + double(ts_beg[1]) / 1000000000.0;
	double tx = double(ts_end[0]) + double(ts_end[1]) / 1000000000.0;

	msg.scan_time = tx - ti;
	msg.time_increment = msg.scan_time / N;

	msg.header.frame_id = frame_id;

	msg.range_min = min_dist;
	msg.range_max = max_dist;

	if (from_zero)
	{
		if (inverted)
		{
			msg.angle_min = 0;
			msg.angle_max = 2 * M_PI * (N - 1) / N;
			msg.angle_increment = M_PI * 2 / N;
		}
		else
		{
			msg.angle_min = 2 * M_PI * (N - 1) / N;
			msg.angle_max = 0;
			msg.angle_increment = -M_PI * 2 / N;
		}
	}
	else
	{
		if (inverted)
		{
			msg.angle_min = -M_PI;
			msg.angle_max = M_PI - (2 * M_PI) / N;
			msg.angle_increment = M_PI * 2 / N;
		}
		else
		{
			msg.angle_min = M_PI;
			msg.angle_max = -M_PI + (2 * M_PI) / N;
			msg.angle_increment = -M_PI * 2 / N;
		}
	}

	if (fans[0]->counterclockwise != 0)
	{
		double d = msg.angle_min;
		msg.angle_min = msg.angle_max;
		msg.angle_max = d;
		msg.angle_increment = -msg.angle_increment;
		msg.angle_min -= msg.angle_increment;
		msg.angle_max -= msg.angle_increment;
	}
	msg.intensities.resize(N);
	msg.ranges.resize(N);
	DataPoint datapoint[N];
	memset(datapoint, 0, sizeof(DataPoint) * N);
	// splitting sectors
	int index = 0;
	bool first = true;
	if (from_zero)
	{
		if (collect_angle > 180)
		{
			index = (360 - collect_angle) / (fans[0]->span / 10.0 / fans[0]->N);
			first = true;
		}
		else if (collect_angle < 180 && collect_angle > 0)
		{
			index = (collect_angle - 0) / (fans[nfan - 1]->span / 10.0 / fans[nfan - 1]->N);
			first = false;
		}
		else if (collect_angle == 0)
		{
			index = 0;
			first = true;
		}
	}
	else
	{
		if (collect_angle > 180)
		{
			index = (collect_angle - 180) / (fans[nfan - 1]->span / 10.0 / fans[nfan - 1]->N);
			first = false;
		}
		else if (collect_angle <= 180)
		{
			index = (180 - collect_angle) / (fans[0]->span / 10.0 / fans[0]->N);
			first = true;
		}
	}
	int pointindex = 0;
	if (first)
	{
		for (int i = index; i < fans[0]->N; i++)
		{
			datapoint[pointindex] = fans[0]->points[i];
			pointindex++;
		}
		for (int i = 1; i < nfan; i++)
		{
			for (int j = 0; j < fans[i]->N; j++)
			{
				datapoint[pointindex] = fans[i]->points[j];
				pointindex++;
			}
		}
		for (int i = 0; i < index; i++)
		{
			datapoint[pointindex] = fans[0]->points[i];
			pointindex++;
		}
	}
	else
	{
		for (int i = index; i < fans[nfan - 1]->N; i++)
		{
			datapoint[pointindex] = fans[nfan - 1]->points[i];
			pointindex++;
		}
		for (int i = 0; i < nfan - 1; i++)
		{
			for (int j = 0; j < fans[i]->N; j++)
			{
				datapoint[pointindex] = fans[i]->points[j];
				pointindex++;
			}
		}
		for (int i = 0; i < index; i++)
		{
			datapoint[pointindex] = fans[nfan - 1]->points[i];
			pointindex++;
		}
	}
	int idx = 0;
	if (reversed)
	{
		for (int i = N - 1; i >= 0; i--)
		{
			double deg = ROSAng(datapoint[i].degree);
			double d = datapoint[i].distance / 1000.0;
			bool custom = false;
			for (unsigned int k = 0; k < custom_masks.size() && !custom; k++)
			{
				if (with_filter && custom_masks[k].min <= deg && deg <= custom_masks[k].max)
					custom = true;
			}

			if (datapoint[i].distance == 0 || d > max_dist || d < min_dist || custom)
				msg.ranges[idx] = std::numeric_limits<float>::infinity();
			else
				msg.ranges[idx] = d;

			msg.intensities[idx] = datapoint[i].confidence;
			idx++;
		}
	}
	else
	{
		for (int i = 0; i <= N - 1; i++)
		{
			double deg = ROSAng(datapoint[i].degree);
			double d = datapoint[i].distance / 1000.0;
			bool custom = false;
			for (unsigned int k = 0; k < custom_masks.size() && !custom; k++)
			{
				if (with_filter && custom_masks[k].min <= deg && deg <= custom_masks[k].max)
					custom = true;
			}

			if (datapoint[i].distance == 0 || d > max_dist || d < min_dist || custom)
				msg.ranges[idx] = std::numeric_limits<float>::infinity();
			else
				msg.ranges[idx] = d;

			msg.intensities[idx] = datapoint[i].confidence;

			idx++;
		}
	}
	filtered_scan = msg;
	if (filter_open)
		filter(msg, filtered_scan, filter_type, max_range, min_range, max_range_difference, filter_window);
	laser_pub->publish(filtered_scan);
}

void PublishCloud(rclcpp::Publisher<sensor_msgs::msg::PointCloud2>::SharedPtr cloud_pub, int nfan, RawData **fans, std::string &frame_id,
				  double max_dist,
				  bool with_filter, double min_ang, double max_ang, int collect_angle)
{
	sensor_msgs::msg::PointCloud2 cloud;

	cloud.header.stamp.sec = fans[0]->ts[0];
	cloud.header.stamp.nanosec = fans[0]->ts[1];

	cloud.header.frame_id = frame_id;

	int N = 0;
	for (int i = 0; i < nfan; i++)
		N += fans[i]->N;

	double min_deg = min_ang * 180 / M_PI;
	double max_deg = max_ang * 180 / M_PI;
	if (with_filter)
	{
		double min_pos, max_pos;
		N = GetCount(nfan, fans, min_deg, max_deg, min_pos, max_pos);
	}

	// x, y, z + intensity channel (as in the ROS 1 sensor_msgs::PointCloud)
	cloud.height = 1;
	cloud.width = N;
	cloud.is_dense = true;
	cloud.is_bigendian = false;
	const char *names[4] = {"x", "y", "z", "intensity"};
	for (int i = 0; i < 4; i++)
	{
		sensor_msgs::msg::PointField f;
		f.name = names[i];
		f.offset = i * 4;
		f.datatype = sensor_msgs::msg::PointField::FLOAT32;
		f.count = 1;
		cloud.fields.push_back(f);
	}
	cloud.point_step = 16;
	cloud.row_step = cloud.point_step * N;
	cloud.data.resize((size_t)cloud.row_step);
	float *pts = reinterpret_cast<float *>(cloud.data.data());

	int idx = 0;
	for (int j = 0; j < nfan; j++)
	{
		for (int i = 0; i < fans[j]->N; i++)
		{
			if (with_filter)
			{
				if (ROSAng(fans[j]->points[i].degree) < min_deg)
					continue;
				if (ROSAng(fans[j]->points[i].degree) > max_deg)
					continue;
			}

			float r = fans[j]->points[i].distance / 1000.0;
			float a = -fans[j]->points[i].degree * M_PI / 180;

			pts[idx * 4 + 0] = cos(a) * r;
			pts[idx * 4 + 1] = sin(a) * r;
			pts[idx * 4 + 2] = 0;
			pts[idx * 4 + 3] = fans[j]->points[i].confidence;
			idx++;
		}
	}
	cloud_pub->publish(cloud);
}

// service call back functions
void stop_motor(const std::shared_ptr<bluesea2::srv::Control::Request> req,
				std::shared_ptr<bluesea2::srv::Control::Response>)
{
	g_should_start = false;
	RCLCPP_INFO(g_node->get_logger(), "Stop motor  index:%ld", (long)req->index);
	char cmd[] = "LSTOPH";
	SendCmd(6, cmd, req->index);
}

void start_motor(const std::shared_ptr<bluesea2::srv::Control::Request> req,
				 std::shared_ptr<bluesea2::srv::Control::Response>)
{
	g_should_start = true;
	char cmd[] = "LSTARH";
	RCLCPP_INFO(g_node->get_logger(), "Start motor  index:%ld", (long)req->index);
	SendCmd(6, cmd, req->index);
}

void switchZone_motor(const std::shared_ptr<bluesea2::srv::DefenceZone::Request> req,
					  std::shared_ptr<bluesea2::srv::DefenceZone::Response>)
{
	char cmd[12] = {0};
	sprintf(cmd, "LSAZN:%xH", req->index);
	RCLCPP_INFO(g_node->get_logger(), "DefenceZone motor  cmd:%s,ip:%s", cmd, req->ip.c_str());
	int index = req->index;
	if (index < 0)
	{
		return;
	}
	SendUdpCmd2(g_reader, (char *)req->ip.c_str(), 12, cmd);
}

bool get_range_param(rclcpp::Node::SharedPtr node, const char *name, Range &range)
{
	std::vector<double> rg;
	if (node->get_parameter(name, rg))
	{
		if (rg.size() == 2 && rg[0] < rg[1])
		{
			range.min = rg[0] * 180 / M_PI;
			range.max = rg[1] * 180 / M_PI;
			return true;
		}
	}
	return false;
}

void getCMDList(CommandList &cmdlist, std::string type, int uuid, int model,
				int init_rpm, double resample_res, int with_smooth, int with_deshadow,
				int enable_alarm_msg, int direction, int unit_is_mm, int with_confidence, int ats)
{
	if (uuid >= 0)
		sprintf(cmdlist.uuid, "LUUIDH");
	if (model >= 0)
		sprintf(cmdlist.model, "LTYPEH");
	if (init_rpm >= 0)
		sprintf(cmdlist.rpm, "LSRPM:%dH", init_rpm);
	if (resample_res >= 0)
	{
		if (resample_res > 0 && resample_res < 1)
			sprintf(cmdlist.res, "LSRES:%dH", (int)(resample_res * 1000));
		else
			sprintf(cmdlist.res, "LSRES:%dH", (int)resample_res);
	}
	if (with_smooth >= 0)
	{
		if (type == "uart")
			sprintf(cmdlist.smooth, "LSSS%dH", with_smooth);
		else
			sprintf(cmdlist.smooth, "LSSMT:%dH", with_smooth);
	}
	if (with_deshadow >= 0)
	{
		if (type == "uart")
			sprintf(cmdlist.fitter, "LFFF%dH", with_deshadow);
		else
			sprintf(cmdlist.fitter, "LSDSW:%dH", with_deshadow);
	}
	if (enable_alarm_msg >= 0)
		sprintf(cmdlist.alarm, "LSPST:%dH", enable_alarm_msg ? 3 : 1);
	if (direction >= 0)
		sprintf(cmdlist.direction, "LSCCW:%dH", direction);
	if (unit_is_mm >= 0)
		sprintf(cmdlist.unit_mm, "%s", unit_is_mm ? "LMDMMH" : "LMDCMH");
	if (with_confidence >= 0)
		sprintf(cmdlist.confidence, "%s", with_confidence ? "LOCONH" : "LNCONH");

	if (ats >= 0)
	{
		if (type == "vpc" || type == "uart")
			sprintf(cmdlist.ats, "LSATS:002H");
		else if (type == "udp")
			sprintf(cmdlist.ats, "LSATS:001H");
	}
}

int autoGetFirstAngle2(HPublish pub, bool from_zero)
{
	PubHub *hub = (PubHub *)pub;
	std::vector<RawData> raws;
	std::string result;
	int ret = -1;

	for (int i = 0; i < hub->nfan; i++)
	{
		ret = autoGetFirstAngle(*(hub->fans[i]), from_zero, raws, result);
		if (ret >= 0 || ret == -2)
		{
			hub->nfan = 0;
			break;
		}
	}
	return ret;
}

int main(int argc, char **argv)
{
	rclcpp::init(argc, argv);
	g_node = std::make_shared<rclcpp::Node>("bluesea2_laser_publisher");
	g_clock = g_node->get_clock();
	signal(SIGINT, closeSignal);

	/*****************************ROS arg start************************************/
	std::string laser_topics[MAX_LIDARS];
	std::string cloud_topics[MAX_LIDARS];

	g_node->declare_parameter<std::string>("topic", "scan");
	g_node->declare_parameter<std::string>("cloud_topic", "cloud");
	g_node->declare_parameter<std::string>("frame_id", "LH_laser");
	g_node->declare_parameter<std::string>("type", "uart");
	g_node->declare_parameter<std::string>("port", "/dev/ttyUSB0");
	g_node->declare_parameter<int>("baud_rate", 500000);
	g_node->declare_parameter<std::vector<int64_t>>("rate_list", std::vector<int64_t>());
	g_node->declare_parameter<int>("lidar_port", 5000);
	g_node->declare_parameter<int>("local_port", 50122);
	g_node->declare_parameter<std::string>("lidar_ip", "192.168.158.98");
	g_node->declare_parameter<bool>("group_listener", false);
	g_node->declare_parameter<std::string>("group_ip", "224.1.1.91");
	g_node->declare_parameter<int>("dev_id", ANYONE);
	g_node->declare_parameter<int>("raw_bytes", 3);
	g_node->declare_parameter<int>("normal_size", -1);
	g_node->declare_parameter<bool>("with_checksum", true);
	g_node->declare_parameter<bool>("inverted", false);
	g_node->declare_parameter<bool>("reversed", false);
	g_node->declare_parameter<double>("zero_shift", 0.0);
	g_node->declare_parameter<bool>("output_scan", true);
	g_node->declare_parameter<bool>("output_cloud", false);
	g_node->declare_parameter<bool>("output_360", true);
	g_node->declare_parameter<bool>("with_angle_filter", false);
	g_node->declare_parameter<bool>("from_zero", false); // true: angle range [0,360), false: [-180,180)
	g_node->declare_parameter<double>("min_angle", -M_PI);
	g_node->declare_parameter<double>("max_angle", M_PI);
	g_node->declare_parameter<double>("min_dist", 0.000);
	g_node->declare_parameter<double>("max_dist", 9999.0);
	g_node->declare_parameter<std::string>("logPath", "/tmp/log");
	g_node->declare_parameter<int>("error_circle", 3);
	g_node->declare_parameter<double>("error_scale", 0.9);
	g_node->declare_parameter<bool>("filter_open", false);
	g_node->declare_parameter<double>("max_range", 20.0);
	g_node->declare_parameter<double>("min_range", 0.5);
	g_node->declare_parameter<double>("max_range_difference", 0.1);
	g_node->declare_parameter<int>("filter_window", 1);
	g_node->declare_parameter<int>("uuid", -1);
	g_node->declare_parameter<int>("model", -1);
	g_node->declare_parameter<int>("rpm", -1);
	g_node->declare_parameter<bool>("hard_resample", false);
	g_node->declare_parameter<bool>("soft_resample", false);
	g_node->declare_parameter<double>("resample_res", -1.0);
	// ROS 1 launch passed these as "true" (bool) while the code read int, so
	// XmlRpc conversion silently fell back to -1 (skip). Keep bool type here
	// to reproduce the exact effective behavior.
	g_node->declare_parameter<bool>("with_smooth", true);
	g_node->declare_parameter<bool>("with_deshadow", true);
	g_node->declare_parameter<int>("alarm_msg", -1);
	g_node->declare_parameter<int>("direction", -1);
	g_node->declare_parameter<int>("unit_is_mm", -1);
	g_node->declare_parameter<int>("with_confidence", -1);
	g_node->declare_parameter<int>("ats", -1);
	for (int i = 1; i < MAX_LIDARS; i++)
	{
		char s[32], t[32], c[32];
		sprintf(s, "lidar%d_ip", i);
		g_node->declare_parameter<std::string>(s, "");
		sprintf(s, "lidar%d_port", i);
		g_node->declare_parameter<int>(s, 0);
		sprintf(s, "topic%d", i);
		sprintf(t, "scan%d", i);
		g_node->declare_parameter<std::string>(s, t);
		sprintf(s, "cloud_topic%d", i);
		sprintf(c, "cloud%d", i);
		g_node->declare_parameter<std::string>(s, c);
	}
	for (int i = 1; i <= 8; i++)
	{
		char s[32];
		sprintf(s, "mask%d", i);
		g_node->declare_parameter<std::vector<double>>(s, std::vector<double>());
	}

	laser_topics[0] = g_node->get_parameter("topic").as_string();
	cloud_topics[0] = g_node->get_parameter("cloud_topic").as_string();
	std::string frame_id = g_node->get_parameter("frame_id").as_string();

	/*****************************ROS arg end************************************/
	/*****************************DATA arg start************************************/
	// LiDAR comm type, could be "uart" or "udp"
	g_type = g_node->get_parameter("type").as_string();
	printf("type is %s\n", g_type.c_str());
	// for serial port comm
	std::string port = g_node->get_parameter("port").as_string();
	int baud_rate = g_node->get_parameter("baud_rate").as_int();

	std::vector<int64_t> rate_list64 = g_node->get_parameter("rate_list").as_integer_array();
	std::vector<int> rate_list(rate_list64.begin(), rate_list64.end());

	// for network comm
	int lidar_ports[MAX_LIDARS], local_port;
	lidar_ports[0] = g_node->get_parameter("lidar_port").as_int();
	local_port = g_node->get_parameter("local_port").as_int();

	std::string lidar_ips[MAX_LIDARS];
	lidar_ips[0] = g_node->get_parameter("lidar_ip").as_string();

	int lidar_count = 1;

	for (int i = 1; i < MAX_LIDARS; i++)
	{
		char s[32];
		sprintf(s, "lidar%d_ip", i);
		lidar_ips[i] = g_node->get_parameter(s).as_string();
		if (lidar_ips[i].length() == 0)
			break;
		sprintf(s, "lidar%d_port", i);
		lidar_ports[i] = g_node->get_parameter(s).as_int();
		if (lidar_ports[i] <= 0)
			break;
		sprintf(s, "topic%d", i);
		laser_topics[i] = g_node->get_parameter(s).as_string();
		sprintf(s, "cloud_topic%d", i);
		cloud_topics[i] = g_node->get_parameter(s).as_string();

		lidar_count++;
	}
	printf("we will connect to %d lidars\n", lidar_count);

	bool is_group_listener = g_node->get_parameter("group_listener").as_bool();
	std::string group_ip = g_node->get_parameter("group_ip").as_string();

	// device identity in data packets, used when multiple lidars connect to single controller
	int dev_id = g_node->get_parameter("dev_id").as_int();

	// raw data format
	int raw_bytes = g_node->get_parameter("raw_bytes").as_int();
	int normal_size = g_node->get_parameter("normal_size").as_int();
	bool with_chk = g_node->get_parameter("with_checksum").as_bool();

	// is lidar inverted
	bool inverted = g_node->get_parameter("inverted").as_bool();
	bool reversed = g_node->get_parameter("reversed").as_bool();

	// zero position
	double zero_shift = g_node->get_parameter("zero_shift").as_double();

	// data output
	bool output_scan = g_node->get_parameter("output_scan").as_bool();
	bool output_cloud = g_node->get_parameter("output_cloud").as_bool();
	bool output_360 = g_node->get_parameter("output_360").as_bool();

	// angle filter
	bool with_angle_filter = g_node->get_parameter("with_angle_filter").as_bool();
	double min_angle = g_node->get_parameter("min_angle").as_double();
	double max_angle = g_node->get_parameter("max_angle").as_double();

	// range limitation
	double min_dist = g_node->get_parameter("min_dist").as_double();
	double max_dist = g_node->get_parameter("max_dist").as_double();
	if (inverted)
	{
		double tmp = min_angle * -1;
		min_angle = max_angle * -1;
		max_angle = tmp;
	}
	if (reversed)
	{
		double tmp = min_angle * -1;
		min_angle = max_angle * -1;
		max_angle = tmp;
	}
	std::vector<Range> custom_masks;
	Range range1, range2;
	if (min_angle < max_angle)
	{
		range1.min = -180;
		range1.max = min_angle / M_PI * 180;
		range2.min = max_angle / M_PI * 180;
		range2.max = 180;
		custom_masks.push_back(range1);
		custom_masks.push_back(range2);
	}

	for (int i = 1; i <= 8; i++)
	{
		char name[32];
		sprintf(name, "mask%d", i);
		Range range;
		if (!get_range_param(g_node, name, range))
			break;
		if (inverted)
		{
			double tmp = range.min * -1;
			range.min = range.max * -1;
			range.max = tmp;
		}
		if (reversed)
		{
			double tmp = range.min * -1;
			range.min = range.max * -1;
			range.max = tmp;
		}
		double min_angle_tmp = min_angle / M_PI * 180;
		double max_angle_tmp = max_angle / M_PI * 180;

		if (min_angle_tmp <= range.min)
		{
			if (range.max <= max_angle_tmp)
			{
			}
			else
			{
				range.max = max_angle_tmp;
			}
		}
		else
		{
			if (range.max <= max_angle_tmp)
			{
				range.min = min_angle_tmp;
			}
			else
			{
				range.min = min_angle_tmp;
				range.max = max_angle_tmp;
			}
		}
		custom_masks.push_back(range);
	}
	// output data format
	bool from_zero = g_node->get_parameter("from_zero").as_bool();
	std::string logPathTmp = g_node->get_parameter("logPath").as_string();
	char logPath[256] = {0};
	if (!logPathTmp.empty())
	{
		struct stat buffer;
		if (stat(logPathTmp.c_str(), &buffer) != 0)
		{
			mkpathAll(logPathTmp, 0755);
		}
		time_t now;
		struct tm *tm_now;
		time(&now);
		tm_now = localtime(&now);
		sprintf(logPath, "%s/log_%04d%02d%02d_%02d%02d%02d.txt", logPathTmp.c_str(), tm_now->tm_year + 1900, tm_now->tm_mon, tm_now->tm_mday, tm_now->tm_hour, tm_now->tm_min, tm_now->tm_sec);
	}
	int error_circle = g_node->get_parameter("error_circle").as_int();
	double error_scale = g_node->get_parameter("error_scale").as_double();

	// from_zero declared above with the other data parameters
	(void)normal_size;
	(void)time_cmp;
	(void)last_ns;

	/*****************************DATA arg end************************************/
	/*******************************FITTER arg start******************************/
	bool filter_open = g_node->get_parameter("filter_open").as_bool();
	int filter_type = 1, filter_window = g_node->get_parameter("filter_window").as_int();
	double max_range = g_node->get_parameter("max_range").as_double();
	double min_range = g_node->get_parameter("min_range").as_double();
	double max_range_difference = g_node->get_parameter("max_range_difference").as_double();
	/*******************************FITTER arg end******************************/
	/*****************************GET arg start************************************/
	int uuid = g_node->get_parameter("uuid").as_int();
	int model = g_node->get_parameter("model").as_int();
	/*****************************GET arg end************************************/
	/*****************************SET arg start************************************/
	int init_rpm = g_node->get_parameter("rpm").as_int();
	bool hard_resample = g_node->get_parameter("hard_resample").as_bool();
	bool with_soft_resample = g_node->get_parameter("soft_resample").as_bool();
	double resample_res = g_node->get_parameter("resample_res").as_double();

	double resample_res2;
	if (!hard_resample)
		resample_res2 = -1;
	else
		resample_res2 = resample_res;

	// ROS 1: launch passed bool while code read int, so the read silently fell
	// back to -1 (skip smooth/deshadow commands). Reproduce effective behavior.
	(void)g_node->get_parameter("with_smooth").as_bool();
	(void)g_node->get_parameter("with_deshadow").as_bool();
	int with_smooth = -1;
	int with_deshadow = -1;
	int enable_alarm_msg = g_node->get_parameter("alarm_msg").as_int();
	int direction = g_node->get_parameter("direction").as_int();
	int unit_is_mm = g_node->get_parameter("unit_is_mm").as_int();
	int with_confidence = g_node->get_parameter("with_confidence").as_int();
	int ats = g_node->get_parameter("ats").as_int();
	/*****************************SET arg end************************************/
	CommandList cmdlist;
	memset(&cmdlist, 0, sizeof(CommandList));
	getCMDList(cmdlist, g_type, uuid, model, init_rpm, resample_res2, with_smooth, with_deshadow, enable_alarm_msg, direction, unit_is_mm, with_confidence, ats);
	printf("ROS VERSION:%s\n", BLUESEA2_VERSION);

	rclcpp::Publisher<sensor_msgs::msg::LaserScan>::SharedPtr laser_pubs[MAX_LIDARS];
	rclcpp::Publisher<sensor_msgs::msg::PointCloud2>::SharedPtr cloud_pubs[MAX_LIDARS];

	for (int i = 0; i < lidar_count; i++)
	{
		if (output_cloud)
		{
			cloud_pubs[i] = g_node->create_publisher<sensor_msgs::msg::PointCloud2>(cloud_topics[i], 50);
		}
		if (output_scan)
		{
			laser_pubs[i] = g_node->create_publisher<sensor_msgs::msg::LaserScan>(laser_topics[i], 50);
		}
	}
	auto stop_srv = g_node->create_service<bluesea2::srv::Control>("stop_motor", stop_motor);
	auto start_srv = g_node->create_service<bluesea2::srv::Control>("start_motor", start_motor);
	auto switchZone_srv = g_node->create_service<bluesea2::srv::DefenceZone>("switchZone_motor", switchZone_motor);

	HParser parsers[MAX_LIDARS];
	PubHub *hubs[MAX_LIDARS] = {NULL};
	for (int i = 0; i < lidar_count; i++)
	{
		parsers[i] = ParserOpen(raw_bytes, with_chk, dev_id, error_circle, error_scale, from_zero, logPath, cmdlist, (char *)lidar_ips[i].c_str(), lidar_ports[i]);
		hubs[i] = new PubHub;
		hubs[i]->nfan = 0;
		hubs[i]->offsetangle = -1;
		hubs[i]->error_num = 0;
		pthread_mutex_init(&hubs[i]->mtx, NULL);
	}

	if (g_type == "uart" || g_type == "vpc")
	{
		int *rates = new int[rate_list.size() + 1];
		for (unsigned int i = 0; i < rate_list.size(); i++)
		{
			rates[i] = rate_list[i];
		}
		rates[rate_list.size()] = 0;
		g_reader = StartUartReader(g_type.c_str(), port.c_str(), baud_rate, rates, parsers[0], hubs[0]);
	}
	else if (g_type == "udp")
	{
		LidarInfo lidars[MAX_LIDARS];
		for (int i = 0; i < lidar_count; i++)
		{
			lidars[i].parser = parsers[i];
			lidars[i].pub = hubs[i];
			strcpy(lidars[i].lidar_ip, lidar_ips[i].c_str());
			lidars[i].lidar_port = lidar_ports[i];
		}
		g_reader = StartUDPReader(g_type.c_str(), local_port, is_group_listener, group_ip.c_str(), lidar_count, lidars);
	}
	else if (g_type == "tcp")
	{
		g_reader = StartTCPReader(lidar_ips[0].c_str(), lidar_ports[0], parsers[0], hubs[0]);
	}
	// get offsetangle
	while (rclcpp::ok())
	{
		rclcpp::spin_some(g_node);
		bool idle = true;
		int ret = -1;
		for (int i = 0; i < lidar_count; i++)
		{
			if (hubs[i]->offsetangle == -1)
			{
				ret = autoGetFirstAngle2(hubs[i], from_zero);
				if (ret >= 0)
				{
					hubs[i]->offsetangle = ret / 10;
					printf("lidar start work,offset angle %d\n", hubs[i]->offsetangle);
				}
				continue;
			}
			RawData *fans[MAX_FANS] = {NULL};
			if (!output_360)
			{
				if (GetFan(hubs[i], with_soft_resample, resample_res, fans))
				{
					if (output_scan)
					{
						PublishLaserScanFan(laser_pubs[i], fans[0], frame_id,
											min_dist, max_dist,
											with_angle_filter, min_angle, max_angle,
											inverted, reversed, zero_shift, from_zero,
											custom_masks, hubs[i]->offsetangle);
					}
					delete fans[0];
					idle = false;
				}
			}
			else
			{
				uint32_t ts_beg[2], ts_end[2];
				int n = GetAllFans(hubs[i], with_soft_resample, resample_res, fans, 0, ts_beg, ts_end, error_circle, error_scale);
				if (n > 0)
				{
					idle = false;
					if (output_scan)
					{
						PublishLaserScan(laser_pubs[i], n, fans, frame_id, min_dist, max_dist,
										 with_angle_filter, min_angle, max_angle,
										 inverted, reversed, zero_shift, from_zero,
										 ts_beg, ts_end, custom_masks, hubs[i]->offsetangle,
										 filter_open, filter_type, max_range, min_range, max_range_difference, filter_window);
					}

					if (output_cloud)
					{
						PublishCloud(cloud_pubs[i], n, fans, frame_id, max_dist,
									 with_angle_filter, min_angle, max_angle, hubs[i]->offsetangle);
					}

					for (int j = 0; j < n; j++)
						delete fans[j];
				}
			}
		}
		if (idle)
		{
			usleep(1000);
		}
	}
	return 0;
}
