#ifndef SWJTUMOVER_MOTOR_SAFETY_H
#define SWJTUMOVER_MOTOR_SAFETY_H

#include <cmath>

namespace motor_safety
{
// All times are steady-clock seconds, independent of ROS /clock.
class Guard
{
public:
    Guard(double command_timeout = 0.5, double feedback_timeout = 0.5,
          double started_at = 0.0)
        : command_timeout_(command_timeout), feedback_timeout_(feedback_timeout),
          started_at_(started_at)
    {
    }

    void command_received(double now)
    {
        have_command_ = true;
        last_command_ = now;
    }

    void invalidate_command() { have_command_ = false; }

    void feedback_received(unsigned motor, double now)
    {
        if (motor < 2)
        {
            have_feedback_[motor] = true;
            last_feedback_[motor] = now;
        }
    }

    double feedback_age(unsigned motor, double now) const
    {
        return now - (have_feedback_[motor] ? last_feedback_[motor] : started_at_);
    }

    bool feedback_fresh(double now) const
    {
        return have_feedback_[0] && have_feedback_[1] &&
               fresh(feedback_age(0, now), feedback_timeout_) &&
               fresh(feedback_age(1, now), feedback_timeout_);
    }

    bool command_fresh(double now) const
    {
        return have_command_ && fresh(now - last_command_, command_timeout_);
    }

    void check_feedback(double now)
    {
        // A communication fault stays latched until the node is restarted.
        if (!fresh(feedback_age(0, now), feedback_timeout_) ||
            !fresh(feedback_age(1, now), feedback_timeout_))
            fault_latched_ = true;
    }

    void latch_fault() { fault_latched_ = true; }
    bool fault_latched() const { return fault_latched_; }

    bool allow_motion(double now) const
    {
        return !fault_latched_ && command_fresh(now) && feedback_fresh(now);
    }

private:
    static bool fresh(double age, double timeout)
    {
        return std::isfinite(age) && age >= 0.0 && age <= timeout;
    }

    double command_timeout_;
    double feedback_timeout_;
    double started_at_;
    bool have_command_ = false;
    double last_command_ = 0.0;
    bool have_feedback_[2] = {false, false};
    double last_feedback_[2] = {0.0, 0.0};
    bool fault_latched_ = false;
};

// Scheduling must never depend on whether a reply arrived.
inline unsigned next_motor(unsigned current) { return current == 0 ? 1 : 0; }
} // namespace motor_safety

#endif
