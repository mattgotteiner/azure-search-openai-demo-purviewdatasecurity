import React from "react";
import { Icon, TooltipHost } from "@fluentui/react";
import { ResponseSensitivityInfo } from "../../api";
import styles from "./ResponseSensitivityBanner.module.css";

interface Props {
    sensitivity: ResponseSensitivityInfo;
}

export const ResponseSensitivityBanner: React.FC<Props> = ({ sensitivity }) => {
    const { overall_label } = sensitivity;
    const displayText = overall_label.display_name || overall_label.name;
    const badgeColor = overall_label.color || "#6c757d"; // Use API color directly, fallback to gray

    return (
        <TooltipHost content={displayText}>
            <div
                style={{
                    display: "inline-flex",
                    alignItems: "center",
                    padding: "4px 8px",
                    backgroundColor: badgeColor,
                    color: "white",
                    borderRadius: "4px",
                    fontSize: "0.8rem",
                    fontWeight: "500",
                    cursor: "pointer",
                    margin: "8px 0"
                }}
            >
                <Icon
                    iconName="ShieldAlert"
                    style={{
                        fontSize: "12px",
                        marginRight: "4px"
                    }}
                />
                {displayText}
            </div>
        </TooltipHost>
    );
};
