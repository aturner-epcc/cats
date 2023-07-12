from argparse import ArgumentParser
from datetime import datetime, timedelta
import requests
import yaml
import sys

from .check_clean_arguments import validate_jobinfo, validate_duration, validate_location
from .optimise_starttime import get_starttime  # noqa: F401
from .CI_api_interface import API_interfaces
from .CI_api_query import get_CI_forecast  # noqa: F401
from .parsedata import avg_carbon_intensity  # noqa: F401
from .carbonFootprint import greenAlgorithmsCalculator

def parse_arguments():
    """
    Parse command line arguments
    :return: [dict] parsed arguments
    """
    parser = ArgumentParser(prog="cats", description="A climate aware job scheduler")

    ### Required

    parser.add_argument("-d", "--duration", type=int, required=True, help="Expected duration of the job in minutes.")

    ### Optional

    parser.add_argument(
        "--api-carbonintensity", type=str,
        help="[optional] which API should be used to obtain carbon intensity forecasts. Overrides `config.yml`."
             "For now, only choice is 'carbonintensity.org.uk' (UK only) (default: 'carbonintensity.org.uk')"
    )  # Note: 'api-carbonintensity' will become 'api_carbonintensity' when parsed by argparse
    parser.add_argument(
        "-l", "--location", type=str,
        help="[optional] location of the computing facility. For the UK, first half of a postcode (e.g. 'M15'), "
             "for other APIs, see doc for exact format. Overrides `config.yml`. "
             "If absent, location based in IP address is used."
    )
    parser.add_argument(
        "--config", type=str,
        help="[optional] path to a config file, default is `config.yml` in current directory. "
             "Config file is required to obtain carbon footprint estimates."
             "template at https://github.com/GreenScheduler/cats/blob/main/config.yml"
    )
    parser.add_argument(
        "--jobinfo", type=str,
        help="Resources used by the job in question, used to estimate total energy usage and carbon footprint. "
             "E.g. 'cpus=2,gpus=0,memory=8,partition=CPU_partition'. "
             "`cpus`: number of CPU cores, `gpus`: number of GPUs, `memory`: memory available in GB, "
             "`partition`: one of the partitions keys in `config.yml`."
    )

    return parser


def main(arguments=None):
    parser = parse_arguments()
    args = parser.parse_args(arguments)

    ##################################
    ## Validate and clean arguments ##
    ##################################

    ## config file
    if args.config:
        with open(args.config, "r") as f:
            config = yaml.safe_load(f)
    else:
        # if no path provided, look for `config.yml` in current directory
        try:
            with open("config.yml", "r") as f:
                config = yaml.safe_load(f)
        except FileNotFoundError:
            config = {}

    ## CI API choice
    list_CI_APIs = ['carbonintensity.org.uk']
    if args.api_carbonintensity:
        choice_CI_API = args.api_carbonintensity
    elif 'api-carbonintensity' in config.keys():
        choice_CI_API = config["api-carbonintensity"]
    else:
        choice_CI_API = 'carbonintensity.org.uk'  # default value is UK

    if choice_CI_API not in list_CI_APIs:
        raise ValueError(f"{choice_CI_API} is not a valid API choice, it needs to be one of {list_CI_APIs}.")

    ## Location
    if args.location:
        location = validate_location(args.location, choice_CI_API)
    elif "location" in config.keys():
        location = validate_location(config["location"], choice_CI_API)
    else:
        r = requests.get("https://ipapi.co/json").json()
        postcode = r["postal"]
        location = validate_location(postcode, choice_CI_API)

    ## Duration
    duration = validate_duration(args.duration)

    ########################
    ## Obtain CI forecast ##
    ########################

    CI_API_interface = API_interfaces[choice_CI_API]
    CI_forecast = get_CI_forecast(location, CI_API_interface)

    #############################
    ## Find optimal start time ##
    #############################

    best_window = get_starttime(CI_forecast, method="windowed", duration=duration)
    sys.stderr.write(str(best_window) + "\n")

    sys.stderr.write(f"Best job start time: {best_window.start}\n")
    print(f"{best_window.start:%Y%m%d%H%M}")  # for POSIX compatibility with at -t

    ################################
    ## Calculate carbon footprint ##
    ################################

    if args.jobinfo:
        jobinfo = validate_jobinfo(args.jobinfo, config)

        if not (jobinfo and config):
            sys.stderr.write("Not enough information to estimate total carbon footprint, both --jobinfo and config files are needed.\n")
        else:
            now_avg_ci = avg_carbon_intensity(
                data=CI_forecast, start=datetime.now(), runtime=timedelta(args.duration)
            )
            estim = greenAlgorithmsCalculator(
                config=config,
                runtime=timedelta(minutes=args.duration),
                averageBest_carbonIntensity=best_window.value, # TODO replace with real carbon intensity
                averageNow_carbonIntensity=now_avg_ci,
                **jobinfo,
            ).get_footprint()

            print(" -!-!- Carbon footprint estimation is a work in progress, coming soon!")
            # Commenting these out while waiting for real carbon intensities
            # print(f"Estimated emmissions for running job now: {estim.now}")
            # msg = (
            #     f"Estimated emmissions for running delayed job: {estim.best})"
            #     f" (- {estim.savings})"
            # )
            # print(msg)
    else:
        sys.stderr.write("Not enough information to estimate total carbon footprint, both --jobinfo and config files are needed.\n")


if __name__ == "__main__":
    main()
