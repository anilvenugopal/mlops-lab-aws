variable "region" {
  type    = string
  default = "us-east-1"
}

variable "env" {
  type    = string
  default = "lab"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "monthly_budget_usd" {
  type    = number
  default = 50
}

variable "alert_email" {
  description = "Where budget and anomaly alerts go"
  type        = string
}
