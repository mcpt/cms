sudo CMS_CONFIG="/home/cms/cms/config/junior.conf" cmsScoringService -c $1 &> err.log & \
sudo CMS_CONFIG="/home/cms/cms/config/junior.conf" cmsChecker &> err.log & \
sudo CMS_CONFIG="/home/cms/cms/config/junior.conf" cmsEvaluationService -c $1 &> err.log & \
sudo CMS_CONFIG="/home/cms/cms/config/junior.conf" cmsContestWebServer -c $1 &> err.log & \
sudo CMS_CONFIG="/home/cms/cms/config/junior.conf" cmsWorker 0 &> err.log & \
sudo CMS_CONFIG="/home/cms/cms/config/junior.conf" cmsProxyService -c $1 &> err.log &
