#!/bin/bash

copy_files() {
    local driver_type=$1 passed_uuid=$2

    echo -e "\033[0m "
    read -p "Rasp Pi IP address: " ip_address
    read -p "The username pls: " username

    # ssh $username@$ip_address "mkdir -p /home/$username/batch-link"
    echo -e "And the password ⊂(◉‿◉)つ"
    scp -pr batch-link/* $username@$ip_address:/home/$username/batch-link
    echo 'Files copied to Pi'

    echo -e "\033[95m "
    echo " __i"
    echo "|---|    "
    echo "|[_]|    "
    echo "|:::|    "
    echo "|:::|    "
    echo "'\   \   "
    echo "  \_=_\ dialing in now"
    echo " "
    echo -e "\033[0m "

    ssh -t $username@$ip_address "\
      echo 'Connected to Raspberry Pi.'; \
      cd /home/$username/batch-link; \
      echo 'Initiate install script on Pi'; \
      bash local-installer.sh ${driver_type} ${passed_uuid};"

}

main() {
    echo -e "\033[32m"
    echo "                                                    
                                                                                                      
                                                                                          
                                                                                          
                                                                                          
                                                                                          
                                            ..                                            
                                      ..:::::::::::.                                      
                                                                                          
                            .:::------==============------:::.                            
                                                                                          
                        ::---===++++*****************+++++===---::                        
                                                                                          
                     ::::-----======+++++++++++++++++++=====-----::::                     
                           .....:::::::------------:::::::.....                           
                    .....::::-----======++++++++++======-----::::.....                    
                   ..:::::----====++++++++******++++++++====----:::::..                   
                           ....::::-------------------:::::....                           
                  ::--===++++*****######################*****++++===--::                  
                                .....::::--------::::.....                                
                 ::--==++**####################################**++==--::                 
                               ....::::::--------::::::....                               
                  ::---====++++****####################****++++====---::                  
                         ....:::::------=========-------::::.....                         
                   ...::::-----====+++++++++++++++++++=====-----::::...                   
                    ....:::::----======++++++++++++======----:::::....                    
                             .....::::::::::::::::::::::.....                             
                     ::-----======+++++++++****++++++++++=====-----::                     
                                                                                          
                        ::---===++++******************+++====---::                        
                                                                                          
                             :::-------=============-----::::.                            
                                                                                          
                                      ..::::::::::..                                      
                                            ..                                            
                                                                                          
                                                                                          
                                BATCH LINK OCTOPRINT INSTALLER                                                     
                                                                                          
                                                                                          
                                                                                      
            "
    echo -e "\033[32m"
    read -p "You got Octoprint on your Pi? (Y/N): " copy_option
    if [[ $copy_option == "Y" || $copy_option == "y" ]]; 
    then
        PASSED_UUID="$1"
        echo "Choose your environment:"
        select env_option in "OCTOPRINT" "KLIPPER"; do
            case $env_option in
                "OCTOPRINT")
                    DRIVER_TYPE="OCTOPRINT"
                    break
                    ;;
                "KLIPPER")
                    DRIVER_TYPE="KLIPPER"
                    break
                    ;;
                *)
                    echo "Invalid option, try again."
                    ;;
            esac
        done
        copy_files "$DRIVER_TYPE" "$PASSED_UUID" 
    else
        echo "Okey, sorry to hear, see ya next time :)"
    fi
}

main