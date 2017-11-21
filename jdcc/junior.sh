sudo CMS_CONFIG="/home/cpt/cms/config/junior.conf" cmsScoringService -c $1 & \
sudo CMS_CONFIG="/home/cpt/cms/config/junior.conf" cmsChecker & \
sudo CMS_CONFIG="/home/cpt/cms/config/junior.conf" cmsEvaluationService -c $1 & \
sudo CMS_CONFIG="/home/cpt/cms/config/junior.conf" cmsContestWebServer -c $1 & \
sudo CMS_CONFIG="/home/cpt/cms/config/junior.conf" cmsWorker 0 & \
sudo CMS_CONFIG="/home/cpt/cms/config/junior.conf" cmsProxyService -c $1 &
