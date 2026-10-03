#pragma once

#include <utility>
#include <vector>

#include <osqp/osqp.h>

struct point_constraint_rect
{
	float xmax = 0;
	float xmin = 0;
	float ymax = 0;
	float ymin = 0;
};

class osqp_utils
{
public:
	osqp_utils(){};

	virtual ~osqp_utils(){};

	void set_ref_points(
		const std::vector<std::pair<double, double>> &ref_points)
	{
		ref_points_ = ref_points;
	}

	void set_bounds_around_refs(const std::vector<point_constraint_rect> &bounds_around_refs)
	{
		bounds_around_refs_ = bounds_around_refs;
	}

	bool solve();

	const std::vector<double> &opt_x() const { return x_; }

	const std::vector<double> &opt_y() const { return y_; }

private:
	void calculate_kernel(std::vector<c_float> *P_data,
						  std::vector<c_int> *P_indices,
						  std::vector<c_int> *P_indptr);

	void calculate_offset(std::vector<c_float> *q);

	void calculate_affine_constraint(std::vector<c_float> *A_data,
									 std::vector<c_int> *A_indices,
									 std::vector<c_int> *A_indptr,
									 std::vector<c_float> *lower_bounds,
									 std::vector<c_float> *upper_bounds);

	void set_primal_warm_start(std::vector<c_float> *primal_warm_start);

	bool optimize_with_osqp(
		const size_t kernel_dim, const size_t num_affine_constraint,
		std::vector<c_float> *P_data, std::vector<c_int> *P_indices,
		std::vector<c_int> *P_indptr, std::vector<c_float> *A_data,
		std::vector<c_int> *A_indices, std::vector<c_int> *A_indptr,
		std::vector<c_float> *lower_bounds, std::vector<c_float> *upper_bounds,
		std::vector<c_float> *q, std::vector<c_float> *primal_warm_start,
		OSQPData *data, OSQPWorkspace **work, OSQPSettings *settings);

private:
	std::vector<std::pair<double, double>> ref_points_;
	std::vector<point_constraint_rect> bounds_around_refs_;

	double weight_fem_pos_deviation_ = 1.0e5;
	double weight_path_length_ = 1.0;
	double weight_ref_deviation_ = 1.0;

	int max_iter_ = 4000;
	double time_limit_ = 0.0;
	bool verbose_ = false;
	bool scaled_termination_ = true;
	bool warm_start_ = true;

	int num_of_points_ = 0;
	int num_of_variables_ = 0;
	int num_of_constraints_ = 0;

	std::vector<double> x_;
	std::vector<double> y_;
};